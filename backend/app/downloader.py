"""
Download engine. Abstracts yt-dlp (video/reel) and gallery-dl (photo
albums, and fallback for profile URLs) behind a single interface, so
the underlying engine can be updated or replaced without touching
API/naming/DB.

IMPORTANT NOTE on supported URLs:
    - yt-dlp only recognizes direct links to a single video/reel/post
      (e.g. facebook.com/.../videos/123..., /reel/123..., /watch/?v=123...).
      It does NOT support a "bare" link to a profile/page (facebook.com/PageName):
      in that case it raises "Unsupported URL".
    - gallery-dl instead supports a profile/page timeline, but mainly
      for PHOTOS (videos remain a weak point for any unofficial tool).
    - To download multiple videos from a profile, the reliable way right
      now is pasting the individual post/video/reel links, not the
      profile link.

Both tools' Facebook extractors follow the site's changes and can break
periodically: this is an intrinsic limitation of any unofficial
downloader, not of this app.
"""
import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yt_dlp

from . import log_buffer
from .config import settings
from .facebook import cookies_file_path


class UnsupportedUrlError(Exception):
    """Neither download engine manages to interpret the given URL."""


_YTDLP_MAX_ATTEMPTS = 3
_YTDLP_RETRY_DELAY_SECONDS = 4


def _derive_post_id_from_url(url: str) -> str:
    """Derives a stable POST identifier directly from the analyzed URL
    — not from gallery-dl's metadata for the individual photo, which
    has proven inconsistent (sometimes already unique by itself even
    among photos from the same album, which produced a different folder
    for EVERY photo instead of grouping them into one). All photos from
    an album are always analyzed starting from the SAME url: using it
    as the basis guarantees the same post_id for all of them, regardless
    of how gallery-dl structures each one's metadata."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return "post"

    query = urllib.parse.parse_qs(parsed.query)
    for key in ("fbid", "story_fbid", "id"):
        if query.get(key):
            return query[key][0]

    segments = [s for s in parsed.path.split("/") if s]
    if segments:
        return segments[-1]

    return "post"


def extract_page_identifier(url: str) -> "str | None":
    """Derives the page's username/vanity-name from the original URL
    (e.g. 'TennisPowerAcademy360' from facebook.com/TennisPowerAcademy360/videos/123).
    Used as a fallback for the poster when yt-dlp doesn't expose the
    profile's numeric ID (frequent, given the Facebook extractor's known
    issues): Facebook's public profile picture endpoint accepts either
    the numeric ID or the username for public Pages."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        return None
    first = segments[0]
    # segments that are never a page/profile name
    excluded = {"share", "watch", "groups", "reel", "photo.php", "profile.php", "permalink.php", "story.php"}
    if first.lower() in excluded or "." in first:
        return None
    return first


def _normalize_profile_url(url: str) -> str:
    """If the URL looks like a "bare" link to a profile/page — domain +
    A SINGLE path segment, e.g. facebook.com/TennisPowerAcademy360, with
    no subpaths like /videos, /reel/123, /watch — adds a trailing slash
    if missing. yt-dlp has shown itself to be more inconsistent without
    one (observed empirically: the same link, with and without a
    trailing slash, gave different results). Doesn't touch other kinds
    of URLs: for a direct link to a post/video/reel the trailing slash
    isn't relevant and isn't added, to avoid risking breaking it."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return url

    segments = [s for s in parsed.path.split("/") if s]
    if len(segments) == 1 and not parsed.path.endswith("/") and "." not in segments[0]:
        parsed = parsed._replace(path=parsed.path + "/")
        return urllib.parse.urlunsplit(parsed)
    return url


_HASHTAG_RE = re.compile(r"#(\w+)", re.UNICODE)


def _extract_hashtags(text: "str | None") -> "tuple[str, list[str]]":
    """Facebook doesn't expose a separate 'tags' field: hashtags live
    inside the caption text (e.g. '...great point! #Tennis #Forehand').
    Extracts them, removes them from the text (which stays clean for the
    description/.nfo <plot>) and returns them as a separate list to use
    as <tag> in the .nfo."""
    if not text:
        return text or "", []

    tags = _HASHTAG_RE.findall(text)
    cleaned = _HASHTAG_RE.sub("", text)
    # cleans up spaces/blank lines left behind by removing the hashtags
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()

    seen = set()
    unique_tags = []
    for tg in tags:
        key = tg.lower()
        if key not in seen:
            seen.add(key)
            unique_tags.append(tg)

    return cleaned, unique_tags


def _ydl_opts(extra: dict | None = None) -> dict:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
    }
    cookies = cookies_file_path()
    if cookies:
        opts["cookiefile"] = str(cookies)
    if extra:
        opts.update(extra)
    return opts


def analyze_url(
    url: str,
    date_from: "date | None" = None,
    date_to: "date | None" = None,
) -> list[dict]:
    """Extracts metadata (without downloading) from a Facebook URL:
    single post, reel, or (via gallery-dl fallback) profile/photo album.
    date_from/date_to filter by publish date, if available.

    Retries a couple of times with a short pause before giving up, then
    tries the alternative engine (gallery-dl) anyway — not just for
    "Unsupported URL" (profile links), but for ANY yt-dlp error,
    including internal parsing failures that happen for example on
    Facebook group posts (page structure different from a normal post):
    previously these were propagated immediately without even trying
    the alternative."""
    url = _normalize_profile_url(url)
    log_buffer.log(1, f"Analysis started: {url}")
    last_exc: "yt_dlp.utils.DownloadError | None" = None

    for attempt in range(_YTDLP_MAX_ATTEMPTS):
        try:
            results = _analyze_with_ytdlp(url, date_from, date_to)
            log_buffer.log(2, f"yt-dlp succeeded on attempt {attempt + 1} for {url}")
            break
        except yt_dlp.utils.DownloadError as exc:
            last_exc = exc
            log_buffer.log(2, f"yt-dlp attempt {attempt + 1}/{_YTDLP_MAX_ATTEMPTS} failed for {url}: {exc}")
            if attempt < _YTDLP_MAX_ATTEMPTS - 1:
                time.sleep(_YTDLP_RETRY_DELAY_SECONDS)
    else:
        # yt-dlp failed with any kind of error -> try gallery-dl as an
        # alternative anyway, not just for profile links
        log_buffer.log(1, f"yt-dlp failed after {_YTDLP_MAX_ATTEMPTS} attempts, trying gallery-dl for {url}")
        results, gallerydl_error = _analyze_with_gallerydl(url)
        if not results:
            detail = (
                f"yt-dlp couldn't read this link after {_YTDLP_MAX_ATTEMPTS} attempts. "
                f"yt-dlp error: {last_exc}. "
                "I also tried the alternative engine (gallery-dl, mainly "
                "for photos), but it couldn't read anything from this URL"
            )
            if gallerydl_error:
                detail += f": {gallerydl_error}"
            else:
                detail += " (no items found — private profile, or empty page?)."
            log_buffer.log(0, f"Analysis failed for {url}: {detail}")
            raise UnsupportedUrlError(detail) from last_exc

    if date_from or date_to:
        results = [
            r for r in results
            if r["publish_date"] is None or _in_range(r["publish_date"].date(), date_from, date_to)
        ]
    results = _disambiguate_duplicate_ids(results)
    log_buffer.log(1, f"Analysis completed for {url}: {len(results)} items found")
    return results


def _disambiguate_duplicate_ids(results: list[dict]) -> list[dict]:
    """If multiple photos/media from the same post end up with the same
    fb_id (happens with gallery-dl: sometimes the ID it exposes is the
    POST's, shared by every photo in an album, not the individual
    photo's) adds a progressive suffix "-1", "-2", etc. to make them
    unique — otherwise they'd overwrite each other when downloaded,
    since they'd share the same file/folder name.

    The suffix is based on order of appearance: as long as gallery-dl
    returns items in the same order for the same URL (the normal case),
    the same ID gets reassigned stably even when re-analyzing the same
    link — so "already downloaded" detection keeps working correctly."""
    total_counts: dict[str, int] = {}
    for r in results:
        total_counts[r["fb_id"]] = total_counts.get(r["fb_id"], 0) + 1

    seen_counts: dict[str, int] = {}
    for r in results:
        base_id = r["fb_id"]
        if total_counts[base_id] > 1:
            seen_counts[base_id] = seen_counts.get(base_id, 0) + 1
            r["fb_id"] = f"{base_id}-{seen_counts[base_id]}"

    return results


def _in_range(d: date, date_from: "date | None", date_to: "date | None") -> bool:
    if date_from and d < date_from:
        return False
    if date_to and d > date_to:
        return False
    return True


def _analyze_with_ytdlp(url: str, date_from: "date | None", date_to: "date | None") -> list[dict]:
    extra = {}
    if date_from:
        extra["dateafter"] = date_from.strftime("%Y%m%d")
    if date_to:
        extra["datebefore"] = date_to.strftime("%Y%m%d")

    with yt_dlp.YoutubeDL(_ydl_opts(extra)) as ydl:
        info = ydl.extract_info(url, download=False)

    if info.get("_type") == "playlist" or "entries" in info:
        entries = [e for e in info.get("entries", []) if e]
    else:
        entries = [info]

    results = []
    for entry in entries:
        publish_dt = _parse_timestamp(entry.get("timestamp")) or _parse_upload_date(entry.get("upload_date"))

        raw_description = entry.get("description") or entry.get("title") or ""
        clean_description, extracted_tags = _extract_hashtags(raw_description)
        existing_tags = [str(tg) for tg in (entry.get("tags") or entry.get("categories") or [])]
        seen_lower = {tg.lower() for tg in existing_tags}
        all_tags = existing_tags + [tg for tg in extracted_tags if tg.lower() not in seen_lower]

        results.append(
            {
                "fb_id": str(entry.get("id")),
                "post_id": str(entry.get("id")),
                "source_url": entry.get("webpage_url") or url,
                "title": entry.get("title") or clean_description or "Untitled",
                "description": clean_description,
                "tags": all_tags,
                "profile": entry.get("uploader") or entry.get("channel") or info.get("uploader") or "unknown",
                "profile_id": entry.get("uploader_id") or entry.get("channel_id") or info.get("uploader_id"),
                "media_type": "reel" if "/reel/" in (entry.get("webpage_url") or url) else "video",
                "publish_date": publish_dt,
                "thumbnail_url": entry.get("thumbnail"),
            }
        )
    return results


def _resolve_share_link(url: str) -> str:
    """Facebook "Share" links (facebook.com/share/p/..., /share/r/...)
    are shortcuts that point to the actual post/photo/reel: yt-dlp
    resolves them internally, but gallery-dl often does NOT recognize
    this short format (observed: 'Unsupported URL' on a /share/p/... link
    that still points to a valid post). Follows the redirect and returns
    the final canonical URL, which gallery-dl is more likely to succeed
    on. If the resolution fails for any reason, returns the original URL
    unchanged (no impact on already-canonical URLs)."""
    if "/share/" not in url:
        return url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.geturl()
    except Exception:  # noqa: BLE001 - a failure here must not block anything
        return url


def _analyze_with_gallerydl(url: str) -> "tuple[list[dict], str | None]":
    """Fallback for profile/page/album URLs: gallery-dl in 'dump' mode
    (--dump-json) downloads nothing, just lists the metadata.
    Returns (results, error_message) — the message is None if everything
    went fine, otherwise it explains why nothing was found (previously
    it was silently ignored, making it impossible to understand the
    reason for a failure)."""
    url = _resolve_share_link(url)
    cmd = ["gallery-dl", "--dump-json", "--no-download", url]
    cookies = cookies_file_path()
    if cookies:
        cmd[1:1] = ["--cookies", str(cookies)]

    log_buffer.log(2, f"gallery-dl command: {' '.join(cmd)}")

    try:
        # shorter timeout than before (120s): this is only a fallback
        # after yt-dlp has already failed 3 times, no point waiting 2
        # minutes for an attempt on a type of URL (Facebook page/profile)
        # that gallery-dl often can't complete anyway — better to fail
        # fast and let the user use the direct link
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        log_buffer.log(0, f"gallery-dl: timeout after 45s for {url}")
        return [], "gallery-dl didn't respond within 45 seconds (timeout) — on a Facebook Page (as opposed to a personal profile) this engine often gets stuck without completing; use a direct link to the single post/video/photo"
    except FileNotFoundError:
        log_buffer.log(0, "gallery-dl is not installed in the container image")
        return [], "gallery-dl is not installed in the container image"

    log_buffer.log(3, f"gallery-dl raw output for {url} (returncode={proc.returncode}):\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}")

    if proc.returncode != 0:
        stderr_snippet = (proc.stderr or "").strip().splitlines()[-1:] or ["no details available"]
        log_buffer.log(0, f"gallery-dl responded with an error for {url}: {stderr_snippet[0][:300]}")
        return [], f"gallery-dl responded with an error: {stderr_snippet[0][:300]}"

    if not proc.stdout.strip():
        return [], "gallery-dl didn't return any item (empty page, private, or unrecognized URL)"

    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], "gallery-dl returned output that couldn't be parsed"

    results = []
    for entry in raw:
        # gallery-dl --dump-json produces, depending on the entry type:
        #   [status, url, metadata]  <- downloadable file (e.g. a photo)
        #   [status, metadata]       <- "container" entry (album/directory)
        # The file's URL may live ONLY in the separate list element
        # (entry[1]), not necessarily inside the metadata itself — it
        # depends on the extractor. Previously I only looked for the URL
        # inside the metadata, which worked for a single-photo post but
        # failed for albums (where gallery-dl uses a different path and
        # the URL only lives in entry[1]): so now I look in both places.
        if isinstance(entry, list):
            entry_url = entry[1] if len(entry) >= 3 and isinstance(entry[1], str) else None
            meta = entry[-1]
        else:
            entry_url = None
            meta = entry

        if not isinstance(meta, dict):
            continue

        # gallery-dl also includes "container" entries (album/post
        # metadata) with no real image URL — previously these were
        # treated as valid photos, ending up with a fake fb_id (the
        # result count, e.g. "0" for the first spurious entry) and no
        # date: the "empty" rows seen in the UI. Discards them.
        image_url = meta.get("url") or entry_url
        if not image_url:
            continue

        fb_id = str(
            meta.get("id")
            or meta.get("photo_id")
            or meta.get("media_id")
            or meta.get("fbid")
            or meta.get("post_id")
        ) if any([meta.get("id"), meta.get("photo_id"), meta.get("media_id"), meta.get("fbid"), meta.get("post_id")]) else None
        if not fb_id:
            # no recognizable ID: not a reliable photo to track anyway
            # (deduplication relies on the ID)
            continue

        raw_description = meta.get("description") or ""
        clean_description, extracted_tags = _extract_hashtags(raw_description)
        existing_tags = [str(tg) for tg in (meta.get("tags") or meta.get("hashtags") or [])]
        seen_lower = {tg.lower() for tg in existing_tags}
        all_tags = existing_tags + [tg for tg in extracted_tags if tg.lower() not in seen_lower]

        # POST identity (to group multiple photos from the same post
        # into the same folder): derived from the analyzed URL, not from
        # the individual photo's metadata (see _derive_post_id_from_url)
        # — this guarantees the same value for every photo in the album
        post_id = _derive_post_id_from_url(url)

        results.append(
            {
                "fb_id": fb_id,
                "post_id": post_id,
                "source_url": image_url,
                "title": meta.get("title") or clean_description or "Untitled",
                "description": clean_description,
                "tags": all_tags,
                "profile": meta.get("username") or meta.get("user") or "unknown",
                "profile_id": meta.get("user_id") or meta.get("owner_id"),
                "media_type": "photo",
                "publish_date": _parse_iso_date(meta.get("date")),
                "thumbnail_url": image_url,
            }
        )
    if results:
        return results, None

    # no results after filtering: instead of continuing to guess how
    # gallery-dl structures entries for this kind of post, show a
    # preview of the RAW output in the error message — so next time it
    # fails we can see the real structure
    raw_preview = proc.stdout.strip()
    if len(raw_preview) > 800:
        raw_preview = raw_preview[:800] + "… (truncated)"
    return [], f"gallery-dl didn't find any photos at this URL. Raw output preview: {raw_preview or '(empty)'}"


def _parse_upload_date(raw: "str | None") -> "datetime | None":
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y%m%d")
    except ValueError:
        return None


def _parse_timestamp(raw) -> "datetime | None":
    """yt-dlp sometimes exposes 'timestamp' (Unix epoch, with the exact
    time) in addition to 'upload_date' (day only) — used when available
    to get the real date/time in the NFO title, not just the default
    midnight."""
    if raw is None:
        return None
    try:
        return datetime.utcfromtimestamp(float(raw))
    except (ValueError, OSError, TypeError):
        return None


def _parse_iso_date(raw) -> "datetime | None":
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.utcfromtimestamp(raw)
        except (ValueError, OSError):
            return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def download_video(url: str, destination: Path) -> Path:
    """Downloads a video/reel with yt-dlp to the exact path already
    rendered by the naming engine (destination already includes the
    folder + filename, without extension)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    opts = _ydl_opts(
        {
            "skip_download": False,
            "outtmpl": str(destination) + ".%(ext)s",
            "merge_output_format": "mp4",
            "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
        }
    )
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    produced = destination.with_suffix(".mp4")
    if not produced.exists():
        matches = list(destination.parent.glob(destination.name + ".*"))
        if matches:
            produced = matches[0]
    return produced


def download_photo_album(url: str, destination_dir: Path) -> list[Path]:
    """Downloads a photo album with gallery-dl (secondary engine, better
    suited to photo posts than yt-dlp).

    Two measures to prevent gallery-dl from creating its own internal
    subfolders inside destination_dir (observed bug: duplicate folder
    with the same ID, e.g. ".../122121.../122121.../filename.jpg" —
    gallery-dl applies its own subfolder structure even with --dest):
    1. "-o directory=[]" explicitly tells gallery-dl not to nest
       anything, and to write files directly into destination_dir;
    2. as a safety net, also searches for files RECURSIVELY (previously
       it only searched the top level with destination_dir.glob("*"),
       which found gallery-dl's subfolder instead of the actual file
       inside it, leaving the unreadable CDN name instead of renaming it)."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["gallery-dl", "-o", "directory=[]", "--dest", str(destination_dir), url]
    cookies = cookies_file_path()
    if cookies:
        cmd[1:1] = ["--cookies", str(cookies)]

    subprocess.run(cmd, check=True, capture_output=True)
    return sorted(p for p in destination_dir.rglob("*") if p.is_file())
