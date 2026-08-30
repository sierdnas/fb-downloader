from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..db import get_session
from ..models import AnalyzedSource, MediaItem

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def list_history(
    profile: "str | None" = None,
    status: "str | None" = None,
    session: Session = Depends(get_session),
) -> list[MediaItem]:
    query = select(MediaItem).order_by(MediaItem.created_at.desc())
    if profile:
        query = query.where(MediaItem.profile == profile)
    if status:
        query = query.where(MediaItem.status == status)
    return session.exec(query).all()


@router.delete("/{fb_id}")
def delete_history_item(fb_id: str, session: Session = Depends(get_session)) -> dict:
    """Removes ONLY the history row (to allow a re-download); doesn't
    touch the file that may already be present on disk."""
    item = session.exec(select(MediaItem).where(MediaItem.fb_id == fb_id)).first()
    if item:
        session.delete(item)
        session.commit()
        return {"deleted": True}
    return {"deleted": False}


@router.get("/sources", response_model=list[AnalyzedSource])
def list_sources(session: Session = Depends(get_session)) -> list[AnalyzedSource]:
    """List of previously analyzed links (profile/post/page), most
    recent first — used by the History tab for the 'Reload' button."""
    query = select(AnalyzedSource).order_by(AnalyzedSource.last_analyzed_at.desc())
    return session.exec(query).all()


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, session: Session = Depends(get_session)) -> dict:
    row = session.get(AnalyzedSource, source_id)
    if row:
        session.delete(row)
        session.commit()
        return {"deleted": True}
    return {"deleted": False}
