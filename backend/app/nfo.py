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
import json
import re
import subprocess
import urllib.error
import urllib.request

from . import log_buffer
from .config import settings
from .facebook import build_cookie_header
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


def _request_headers() -> dict:
    """Common headers for the direct HTTP requests this module makes:
    a User-Agent, plus the user's Facebook session cookies when a
    cookies.txt is configured — some of Facebook's endpoints behave
    differently for anonymous vs authenticated requests (e.g. handing
    back the generic placeholder silhouette instead of the real picture
    for an anonymous request to a profile that requires login to view)."""
    headers = {"User-Agent": "Mozilla/5.0"}
    cookie_header = build_cookie_header()
    if cookie_header:
        headers["Cookie"] = cookie_header
    return headers


def _append_access_token(url: str) -> str:
    """Adds the optional Graph API access token (FACEBOOK_ACCESS_TOKEN,
    see config.py) to a graph.facebook.com URL, when configured.
    Session cookies do NOT authenticate Graph API calls — this is the
    real credential that endpoint expects; without it,
    graph.facebook.com/{id}/picture has been observed returning the
    generic silhouette placeholder even for pages that definitely have
    a real photo."""
    if not settings.facebook_access_token:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}access_token={settings.facebook_access_token}"


def _mask_url_for_log(url: str) -> str:
    """Strips the access_token value out of a URL before logging it —
    the in-app Log tab is meant to be safely copy-pasteable for
    debugging (including sharing it with someone else, or with an AI
    assistant), and a Graph API token is a credential, not something
    that should ever end up there in the clear."""
    return re.sub(r"([?&]access_token=)[^&]+", r"\1***", url)


def _download_image(url: str, dest_path: Path) -> "Path | None":
    """Downloads an image from any URL and saves it to dest_path.
    Returns None (without raising) for any kind of failure: network,
    invalid URL, non-image response — used by "best effort" functions
    where missing artwork isn't an error. Every attempt is logged (at
    level 2, or level 0 on failure) so a failure can actually be
    diagnosed from the Log tab instead of failing silently."""
    log_url = _mask_url_for_log(url)
    try:
        req = urllib.request.Request(url, headers=_request_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if resp.status == 200 and content_type.startswith("image/"):
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(resp.read())
                log_buffer.log(2, f"Image downloaded: {log_url} -> {dest_path.name}")
                return dest_path
            log_buffer.log(0, f"Image download got an unexpected response for {log_url}: status={resp.status}, content-type={content_type!r}")
    except urllib.error.HTTPError as exc:
        body_snippet = ""
        try:
            body_snippet = exc.read(300).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        log_buffer.log(0, f"Image download failed for {log_url}: HTTP {exc.code} {exc.reason}{' — ' + body_snippet if body_snippet else ''}")
    except Exception as exc:  # noqa: BLE001 - missing artwork is not a fatal error
        log_buffer.log(0, f"Image download failed for {log_url}: {type(exc).__name__}: {exc}")
    return None


def _fetch_facebook_picture_url(candidate: str) -> "tuple[str | None, bool]":
    """Queries graph.facebook.com's picture metadata (with redirect=false)
    to get BOTH the actual image URL and whether it's Facebook's generic
    placeholder silhouette — returned (with a normal 200 OK and a real
    image/jpeg body!) when the account has no custom profile picture, or
    often also when the request lacks permissions Facebook now expects
    even for "public" pictures. Without this check, that generic gray
    silhouette gets saved as if it were a real poster, indistinguishable
    from a genuine photo by HTTP status/content-type alone. Includes the
    user's session cookies when available, and the Graph API access
    token when configured (see _append_access_token — session cookies
    alone have NOT been sufficient to avoid the silhouette in practice).
    Returns (url, is_silhouette); url is None if the metadata call itself fails."""
    meta_url = _append_access_token(f"https://graph.facebook.com/{candidate}/picture?width=720&height=720&redirect=false")
    log_url = _mask_url_for_log(meta_url)
    try:
        req = urllib.request.Request(meta_url, headers=_request_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        data = payload.get("data", {})
        return data.get("url"), bool(data.get("is_silhouette"))
    except Exception as exc:  # noqa: BLE001 - falls back to a direct download attempt
        log_buffer.log(2, f"Could not check picture metadata for {candidate} ({log_url}), will try a direct download instead: {exc}")
        return None, False


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
    error. Skips (never saves) Facebook's generic placeholder silhouette
    — see _fetch_facebook_picture_url."""
    poster_path = profile_dir / "poster.jpg"
    if poster_path.exists():
        # don't overwrite a poster that's already there (maybe added manually)
        return poster_path

    real_candidates = [c for c in candidate_ids if c]
    if not real_candidates:
        log_buffer.log(0, f"Show poster skipped for {profile_dir.name}: no candidate ID/username available (yt-dlp exposed no profile_id, and no username could be extracted from the URL)")
        return None

    log_buffer.log(2, f"Show poster: trying candidates {real_candidates} for {profile_dir.name}")
    for candidate in real_candidates:
        image_url, is_silhouette = _fetch_facebook_picture_url(candidate)
        if is_silhouette:
            log_buffer.log(2, f"Show poster: '{candidate}' has no real profile picture (Facebook returned the generic placeholder silhouette) — skipping")
            continue
        if not image_url:
            # metadata check itself failed (network hiccup, endpoint
            # changed...): falls back to the direct picture URL anyway,
            # best-effort — it just won't have the silhouette check
            image_url = _append_access_token(f"https://graph.facebook.com/{candidate}/picture?width=720&height=720")
        result = _download_image(image_url, poster_path)
        if result:
            return result

    log_buffer.log(0, f"Show poster: all candidates failed or had no real picture for {profile_dir.name} ({real_candidates})")
    return None


def write_season_poster(season_dir: Path, show_poster_path: "Path | None") -> "Path | None":
    """Copies the show's poster (profile picture) into the season
    folder too, so Jellyfin shows branded artwork for each season
    instead of falling back to a generic/blank default when no
    season-specific image is set. There's no real per-season Facebook
    asset to use instead (seasons are our own construct — one per
    publish year), so this reuses the same show-level image. Skips
    entirely if the show poster itself isn't available, and never
    overwrites a season poster that's already there."""
    if not show_poster_path or not show_poster_path.exists():
        return None

    season_poster_path = season_dir / "poster.jpg"
    if season_poster_path.exists():
        return season_poster_path

    try:
        season_dir.mkdir(parents=True, exist_ok=True)
        season_poster_path.write_bytes(show_poster_path.read_bytes())
        log_buffer.log(2, f"Season poster copied from show poster -> {season_dir.name}/poster.jpg")
        return season_poster_path
    except OSError as exc:  # noqa: BLE001 - a missing season poster is not a fatal error
        log_buffer.log(0, f"Season poster copy failed for {season_dir.name}: {exc}")
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


def _ffprobe_duration(video_path: Path) -> "float | None":
    """Video duration in seconds via ffprobe, or None if it can't be
    determined (corrupt file, ffprobe missing, etc.)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=True)
        return float(result.stdout.strip())
    except Exception:  # noqa: BLE001
        return None


def write_episode_thumbnail(video_path: Path, target_seconds: float = 10.0) -> "Path | None":
    """Extracts a frame as a local thumbnail for the episode, named per
    the Jellyfin/Kodi convention ("<video-filename>-thumb.jpg" in the
    same folder) — Jellyfin uses this local image directly instead of
    generating its own, which fixes short clips ending up with no
    thumbnail at all in the library grid (Jellyfin's own automatic
    extraction can fail or land past the end of very short videos).

    Best-effort: for clips shorter than target_seconds, captures a frame
    partway through instead (never past the end, with a small safety
    margin) rather than failing outright. Doesn't overwrite an existing
    thumbnail (e.g. one you replaced by hand)."""
    thumb_path = video_path.with_name(f"{video_path.stem}-thumb.jpg")
    if thumb_path.exists():
        return thumb_path

    duration = _ffprobe_duration(video_path)
    if duration is None or duration <= 0:
        capture_at = target_seconds
    elif duration <= target_seconds:
        # short clip: grabs a frame partway through instead of at a fixed
        # point that might not exist (with a small margin from the very
        # end, which is sometimes a black/blank frame)
        capture_at = max(duration * 0.5, 0.1)
        capture_at = min(capture_at, max(duration - 0.2, 0.1))
    else:
        capture_at = target_seconds

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(capture_at),
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",
        str(thumb_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
    except Exception as exc:  # noqa: BLE001 - a missing thumbnail is not a fatal error
        log_buffer.log(0, f"Thumbnail extraction failed for {video_path.name}: {exc}")
        return None

    if thumb_path.exists() and thumb_path.stat().st_size > 0:
        log_buffer.log(2, f"Thumbnail extracted for {video_path.name} at {capture_at:.1f}s -> {thumb_path.name}")
        return thumb_path
    return None
