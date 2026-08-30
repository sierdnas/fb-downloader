from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from .. import queue_worker
from ..db import get_session
from ..models import MediaItem
from ..naming import format_display_title
from ..schemas import DownloadRequest

router = APIRouter(prefix="/api/download", tags=["download"])


@router.post("")
def start_download(req: DownloadRequest, session: Session = Depends(get_session)) -> dict:
    """Queues the selected items and returns IMMEDIATELY (doesn't wait
    for the downloads to finish): the actual download happens in the
    background worker (see queue_worker.py). Follow progress with
    GET /api/queue.

    Explicitly selecting an item that's already been downloaded forces a
    RE-download (cleanup of old files including .nfo, handled by the worker)."""
    queued = []

    for item in req.items:
        if item.media_type not in req.media_types:
            continue

        existing = session.exec(select(MediaItem).where(MediaItem.fb_id == item.fb_id)).first()
        record = existing or MediaItem(
            fb_id=item.fb_id,
            source_url=item.source_url,
            profile=item.profile,
            media_type=item.media_type,
            title=format_display_title(item.fb_id, item.publish_date),
            description=item.description,
            tags=item.tags or [],
            publish_date=item.publish_date,
            relative_path="",  # computed by the worker at download time
        )
        record.status = "queued"
        record.error_message = None
        session.add(record)
        session.commit()

        queue_worker.enqueue(item)
        queued.append({"fb_id": item.fb_id, "status": "queued"})

    return {"queued": queued, "queue_size": queue_worker.queue_size()}
