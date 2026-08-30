"""
In-process download queue: no Redis/Celery (overkill for a single-user
tool), just a worker thread that consumes a queue.Queue and writes
progress status to SQLite, so the UI can poll it.

/api/download queues and returns immediately; the actual download
happens here, in the background, one or more items at a time depending
on WORKER_COUNT.
"""
import queue
import threading
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from . import downloader, log_buffer, nfo
from .config import settings
from .db import engine
from .episodes import VIDEO_LIKE_TYPES, next_episode_number, season_for_date
from .models import MediaItem
from .naming import build_relative_path, format_display_title, slugify_physical
from .schemas import MediaPreview

_task_queue: "queue.Queue[MediaPreview]" = queue.Queue()
_started = False
_lock = threading.Lock()

WORKER_COUNT = 2  # parallel downloads: enough not to be too slow
                   # without overwhelming the NAS's connection or Facebook itself


def start_worker() -> None:
    """Starts the worker threads once (called at FastAPI startup)."""
    global _started
    with _lock:
        if _started:
            return
        for _ in range(WORKER_COUNT):
            t = threading.Thread(target=_worker_loop, daemon=True)
            t.start()
        _started = True


def enqueue(item: MediaPreview) -> None:
    _task_queue.put(item)


def queue_size() -> int:
    return _task_queue.qsize()


def _worker_loop() -> None:
    while True:
        item = _task_queue.get()
        try:
            _process_item(item)
        except Exception:  # noqa: BLE001 - must never kill the worker thread
            pass
        finally:
            _task_queue.task_done()


def _root_for(media_type: str) -> Path:
    """Correct root depending on media type: photos go under
    photo_media_root (dedicated, separate folder), video/reel under
    media_root as always."""
    return settings.photo_media_root if media_type == "photo" else settings.media_root


def _process_item(item: MediaPreview) -> None:
    # each task gets its own Session: SQLite/SQLModel isn't thread-safe
    # if a session is shared between different threads
    with Session(engine) as session:
        existing = session.exec(select(MediaItem).where(MediaItem.fb_id == item.fb_id)).first()

        # NOTE: we don't check existing.status == "done" here, because
        # the router (routers/download.py) already overwrites it to
        # "queued" as soon as it accepts the request — by the time the
        # worker gets around to reading it, that information is already
        # lost (a race condition discovered while testing re-download of
        # a photo album). relative_path/downloaded_at, on the other
        # hand, aren't touched by the router, so they remain a reliable
        # signal that "a completed download already existed before this
        # request".
        if existing and existing.relative_path and existing.downloaded_at:
            _cleanup_existing_files(existing)

        is_video_like = item.media_type in VIDEO_LIKE_TYPES
        ext = "jpg" if item.media_type == "photo" else "mp4"
        folder_template = settings.folder_template_photo if item.media_type == "photo" else settings.folder_template_video
        filename_template = settings.filename_template_photo if item.media_type == "photo" else settings.filename_template

        season = season_for_date(item.publish_date) if is_video_like else None
        if is_video_like:
            episode = existing.episode if (existing and existing.episode) else next_episode_number(
                session, item.profile, season
            )
        else:
            episode = None

        relative_path = build_relative_path(
            folder_template,
            filename_template,
            ext,
            publish_date=item.publish_date,
            profile=item.profile,
            title=item.title,
            media_id=item.fb_id,
            media_type=item.media_type,
            date_format=settings.date_format,
            season=season,
            post_id=item.post_id,
        )

        record = existing or MediaItem(
            fb_id=item.fb_id,
            source_url=item.source_url,
            profile=item.profile,
            media_type=item.media_type,
            title=format_display_title(item.fb_id, item.publish_date),
            description=item.description,
            tags=item.tags or [],
            publish_date=item.publish_date,
            relative_path=relative_path,
        )
        record.description = item.description
        record.tags = item.tags or []
        record.season = season
        record.episode = episode
        record.status = "downloading"
        record.error_message = None
        session.add(record)
        session.commit()

        log_buffer.log(1, f"Download started: {item.media_type} {item.fb_id} ({item.profile}) -> {relative_path}")

        try:
            final_path = _dispatch_download(item.media_type, item.source_url, relative_path)

            if settings.generate_nfo and is_video_like:
                profile_dir = settings.media_root / slugify_physical(item.profile)
                nfo.write_tvshow_nfo(profile_dir, item.profile)
                nfo.write_show_poster(
                    profile_dir,
                    [item.profile_id, downloader.extract_page_identifier(item.source_url)],
                )
                nfo.write_show_fanart(profile_dir, item.thumbnail_url)
                nfo.write_episode_nfo(
                    final_path,
                    fb_id=item.fb_id,
                    season=season,
                    episode=episode,
                    publish_date=item.publish_date,
                    profile=item.profile,
                    media_type=item.media_type,
                    source_url=item.source_url,
                    description=item.description,
                    tags=item.tags,
                )

            record.status = "done"
            record.relative_path = str(final_path.relative_to(_root_for(item.media_type)))
            record.file_size_bytes = final_path.stat().st_size if final_path.exists() else None
            record.downloaded_at = datetime.utcnow()
            log_buffer.log(1, f"Download completed: {item.fb_id} -> {record.relative_path}")
        except Exception as exc:  # noqa: BLE001
            record.status = "error"
            record.error_message = str(exc)
            log_buffer.log(0, f"Download failed: {item.media_type} {item.fb_id} ({item.profile}): {exc}")

        session.add(record)
        session.commit()


def _cleanup_existing_files(record: MediaItem) -> None:
    """Removes ONLY the file matching this specific media item (same
    base name in the same folder) before re-downloading — never the
    whole folder: since photos from the same post share a folder
    (grouped by post_id), deleting it entirely when re-downloading ONE
    photo would also delete the other sibling photos that weren't
    re-selected."""
    if not record.relative_path:
        return
    full_path = _root_for(record.media_type) / record.relative_path
    if not full_path.parent.exists():
        return

    target_stem = full_path.stem
    for sibling in full_path.parent.iterdir():
        if sibling.is_file() and sibling.stem == target_stem:
            try:
                sibling.unlink()
            except FileNotFoundError:
                pass


def _dispatch_download(media_type: str, url: str, relative_path: str) -> Path:
    full_path = _root_for(media_type) / relative_path

    if media_type in VIDEO_LIKE_TYPES:
        stem_path = full_path.with_suffix("")
        return downloader.download_video(url, stem_path)

    if media_type == "photo":
        post_dir = full_path.parent
        produced = downloader.download_photo_album(url, post_dir)
        if not produced:
            return full_path

        # moves every file found DIRECTLY into post_dir (not just
        # "rename in place"): even if gallery-dl had nested it inside
        # one of its own internal subfolders despite "-o directory=[]",
        # the final result stays flat and clean regardless. The first
        # file becomes "{id}.ext", any others (multi-photo album)
        # "{id}-2.ext", "-3", etc. — keeping each one's original
        # extension (not always .jpg).
        base_stem = full_path.stem
        moved: list[Path] = []
        for i, produced_path in enumerate(produced, start=1):
            suffix = "" if i == 1 else f"-{i}"
            new_path = post_dir / f"{base_stem}{suffix}{produced_path.suffix}"
            if produced_path != new_path:
                produced_path.rename(new_path)
            moved.append(new_path)

        # cleans up any empty subfolders left behind by gallery-dl after
        # moving all the files out
        for leftover_dir in sorted(post_dir.rglob("*"), reverse=True):
            if leftover_dir.is_dir():
                try:
                    leftover_dir.rmdir()
                except OSError:
                    pass  # not empty for some reason: leave it alone

        return moved[0]

    raise ValueError(f"Unsupported media type: {media_type}")
