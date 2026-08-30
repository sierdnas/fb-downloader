"""
Generates Jellyfin metadata in "TV show" format:
    - tvshow.nfo in the profile folder (Show = Facebook profile),
      written once (idempotent)
    - one .nfo per episode next to each downloaded video/reel
      (Season = publish year, Episode = progressive number)

PHOTOS don't use NFO: Jellyfin's "Photos" library type doesn't read
them, so they stay organized in {profile}/Photo with no metadata generated.
"""
from pathlib import Path
from xml.sax.saxutils import escape
import urllib.request

from .naming import clean_display_title, format_display_title


def write_tvshow_nfo(profile_dir: Path, profile: str) -> Path:
    """Writes tvshow.nfo in the profile folder. Doesn't overwrite if
    already present, so as not to lose any manual changes made in
    Jellyfin (e.g. a custom poster or description)."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    nfo_path = profile_dir / "tvshow.nfo"
    if nfo_path.exists():
        return nfo_path

    display_name = clean_display_title(profile)
    xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<tvshow>
    <title>{escape(display_name)}</title>
    <studio>Facebook</studio>
</tvshow>
"""
    nfo_path.write_text(xml, encoding="utf-8")
    return nfo_path


def _download_image(url: str, dest_path: Path) -> "Path | None":
    """Downloads an image from any URL and saves it to dest_path.
    Returns None (without raising) for any kind of failure: network,
    invalid URL, non-image response — used by "best effort" functions
    where missing artwork isn't an error."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if resp.status == 200 and content_type.startswith("image/"):
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(resp.read())
                return dest_path
    except Exception:  # noqa: BLE001 - missing artwork is not a fatal error
        pass
    return None


def write_show_poster(profile_dir: Path, candidate_ids: "list[str | None]") -> "Path | None":
    """Attempts to download the Facebook profile picture as poster.jpg
    for the show (best-effort, doesn't block the download if it fails).

    Uses the public graph.facebook.com/{id}/picture endpoint, which
    doesn't require authentication for public Page profile pictures —
    accepts either the numeric ID (when yt-dlp exposes it, rare) or the
    username/vanity-name derived from the URL (more reliable, see
    downloader.extract_page_identifier). Tries each candidate in order
    until one works; if none works, or if the profile is private/the
    endpoint changed, it does nothing: a missing poster is not a fatal
    error."""
    poster_path = profile_dir / "poster.jpg"
    if poster_path.exists():
        # don't overwrite a poster that's already there (maybe added manually)
        return poster_path

    for candidate in candidate_ids:
        if not candidate:
            continue
        url = f"https://graph.facebook.com/{candidate}/picture?width=720&height=720"
        result = _download_image(url, poster_path)
        if result:
            return result
    return None


def write_show_fanart(profile_dir: Path, thumbnail_url: "str | None") -> "Path | None":
    """Background (fanart) for the show — NOT the real Facebook Page
    cover photo: that requires authenticated access to the Graph API
    with special permissions (app review), not obtainable with a simple
    scraping trick. As an honest substitute, uses the thumbnail of the
    first video downloaded for that profile (when yt-dlp exposes it).
    Doesn't overwrite an existing fanart."""
    if not thumbnail_url:
        return None
    fanart_path = profile_dir / "fanart.jpg"
    if fanart_path.exists():
        return fanart_path
    return _download_image(thumbnail_url, fanart_path)


def write_episode_nfo(
    media_path: Path,
    *,
    fb_id: str,
    season: int,
    episode: int,
    publish_date,
    profile: str,
    media_type: str,
    source_url: str,
    description: "str | None" = None,
    tags: "list[str] | None" = None,
) -> Path:
    """Writes the episode .nfo next to the video file, with the same
    base name (e.g. 2026-08-16-23-50_2128650394390172.nfo).

    - <title>: date, time, and Facebook ID (e.g. "2026-08-16 23-50
      2128650394390172"), readable and with no underscores — underscores
      only exist in the physical filename on disk. The exact same format
      used by the web UI for the "Title" column.
    - <plot>: the post's text (original caption/description), shown by
      Jellyfin in the "Details" field.
    - <tag>: one for the media type (video/reel) + one for each tag/
      hashtag of the post, when yt-dlp manages to extract them (not
      always available: Facebook doesn't expose them in every post format)."""
    nfo_path = media_path.with_suffix(".nfo")

    aired = publish_date.strftime("%Y-%m-%d") if publish_date else ""
    display_title = format_display_title(fb_id, publish_date)
    plot = clean_display_title(description) if description else ""

    tag_values = [media_type] + [str(tg) for tg in (tags or []) if str(tg).strip()]
    tag_lines = "\n".join(f"    <tag>{escape(clean_display_title(tg))}</tag>" for tg in tag_values)

    xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<episodedetails>
    <title>{escape(display_title)}</title>
    <showtitle>{escape(clean_display_title(profile))}</showtitle>
    <season>{season}</season>
    <episode>{episode}</episode>
    <aired>{aired}</aired>
    <plot>{escape(plot)}</plot>
{tag_lines}
    <uniqueid type="facebook" default="true">{escape(fb_id)}</uniqueid>
    <source>{escape(source_url)}</source>
</episodedetails>
"""
    nfo_path.write_text(xml, encoding="utf-8")
    return nfo_path
