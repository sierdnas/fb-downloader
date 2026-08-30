"""
Season and episode calculation to organize video/reel as a TV show per
profile in Jellyfin (Show = profile, Season = year, Episode = post).
Photos are not part of this scheme.
"""
from datetime import date, datetime

from sqlmodel import Session, select

from .models import MediaItem

VIDEO_LIKE_TYPES = ("video", "reel")


def season_for_date(publish_date: "datetime | date | None") -> int:
    """Publish year, used as the season number. 0 (Season 0, the
    "specials" convention in Jellyfin) if the date isn't available."""
    return publish_date.year if publish_date else 0


def next_episode_number(session: Session, profile: str, season: int) -> int:
    """Next available episode number for profile+season, computed by
    counting the video/reel items already successfully downloaded for
    that combination (progressive, not necessarily tied to the exact
    chronological order if analyses of different links are mixed)."""
    query = select(MediaItem).where(
        MediaItem.profile == profile,
        MediaItem.season == season,
        MediaItem.media_type.in_(VIDEO_LIKE_TYPES),
        MediaItem.status == "done",
    )
    return len(session.exec(query).all()) + 1
