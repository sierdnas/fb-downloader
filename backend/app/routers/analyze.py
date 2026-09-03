from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .. import analyze_jobs, translate
from ..config import settings
from ..db import get_session
from ..models import AnalyzedSource, MediaItem
from ..naming import build_relative_path, format_display_title
from ..schemas import AnalyzeJobStatus, AnalyzeRequest, MediaPreview

router = APIRouter(prefix="/api/analyze", tags=["analyze"])


@router.post("", response_model=AnalyzeJobStatus)
def start_analyze(req: AnalyzeRequest) -> AnalyzeJobStatus:
    """Starts the analysis in the BACKGROUND and returns immediately with
    a job_id: for profiles/pages with many posts, yt-dlp has to query
    every single item and it can take minutes. The HTTP request is no
    longer left blocked waiting — follow progress with
    GET /api/analyze/{job_id}."""
    job_id = analyze_jobs.start_job(req.url, req.date_from, req.date_to)
    return AnalyzeJobStatus(job_id=job_id, status="running")


@router.get("/{job_id}", response_model=AnalyzeJobStatus)
def get_analyze_status(job_id: str, session: Session = Depends(get_session)) -> AnalyzeJobStatus:
    job = analyze_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found (maybe expired)")

    if job["status"] == "running":
        return AnalyzeJobStatus(job_id=job_id, status="running")

    if job["status"] == "error":
        return AnalyzeJobStatus(job_id=job_id, status="error", error=job["error"])

    # status == "done": builds the MediaPreviews NOW (not in the
    # background thread), so "already_downloaded" reflects the most
    # recent DB state even if you downloaded something else in the meantime
    raw_items = job["raw_items"]
    if not raw_items:
        return AnalyzeJobStatus(job_id=job_id, status="error", error="No media found for this URL")

    try:
        profile_name = raw_items[0]["profile"]
        previews: list[MediaPreview] = []

        for item in raw_items:
            existing = session.exec(select(MediaItem).where(MediaItem.fb_id == item["fb_id"])).first()

            ext = "jpg" if item["media_type"] == "photo" else "mp4"
            folder_template = (
                settings.folder_template_photo if item["media_type"] == "photo" else settings.folder_template_video
            )
            filename_template = (
                settings.filename_template_photo if item["media_type"] == "photo" else settings.filename_template
            )
            predicted_path = build_relative_path(
                folder_template,
                filename_template,
                ext,
                publish_date=item["publish_date"],
                profile=item["profile"],
                title=item["title"],
                media_id=item["fb_id"],
                media_type=item["media_type"],
                date_format=settings.date_format,
                post_id=item.get("post_id"),
            )

            description = item.get("description")
            if settings.translate_description and description:
                description = translate.translate_text(description, settings.ui_language)

            previews.append(
                MediaPreview(
                    fb_id=item["fb_id"],
                    post_id=item.get("post_id"),
                    source_url=item["source_url"],
                    profile=item["profile"],
                    profile_id=item.get("profile_id"),
                    media_type=item["media_type"],
                    title=item["title"],
                    display_title=format_display_title(item["fb_id"], item["publish_date"]),
                    description=description,
                    tags=item.get("tags") or [],
                    publish_date=item["publish_date"],
                    thumbnail_url=item.get("thumbnail_url"),
                    already_downloaded=bool(existing and existing.status == "done"),
                    predicted_path=predicted_path,
                )
            )

        _record_analyzed_source(session, job["url"], profile_name, len(previews))

        return AnalyzeJobStatus(job_id=job_id, status="done", profile=profile_name, items=previews)
    except Exception as exc:  # noqa: BLE001 - NEVER a raw 500: always a readable error with the real detail
        return AnalyzeJobStatus(
            job_id=job_id,
            status="error",
            error=f"Internal error while building results ({type(exc).__name__}): {exc}",
        )


def _record_analyzed_source(session: Session, url: str, profile: str, item_count: int) -> None:
    """Keeps track of analyzed links (profiles/posts/pages) so the user
    can reload them with one click from the History tab instead of
    having to find/re-paste them by hand."""
    existing = session.exec(select(AnalyzedSource).where(AnalyzedSource.url == url)).first()
    now = datetime.utcnow()
    if existing:
        existing.profile = profile
        existing.last_item_count = item_count
        existing.last_analyzed_at = now
        session.add(existing)
    else:
        session.add(
            AnalyzedSource(
                url=url,
                profile=profile,
                last_item_count=item_count,
                first_analyzed_at=now,
                last_analyzed_at=now,
            )
        )
    session.commit()
