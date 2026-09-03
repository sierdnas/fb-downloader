"""Central app configuration, read from environment variables / .env file."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # NOTE: no app_port field here — the internal port is fixed (8686,
    # set in the Dockerfile). The port exposed on the host is changed
    # ONLY via APP_PORT in .env/docker-compose.yml (not read by this app).

    config_dir: Path = Path("/config")
    media_root: Path = Path("/media/facebook")
    # SEPARATE root for photos/images: Jellyfin doesn't handle photos like
    # videos (no NFO/show/season data for photos), so they live in a
    # completely distinct folder tree from videos, so the two Jellyfin
    # libraries (TV Shows / Photos) can point at two different root
    # folders with no overlap.
    photo_media_root: Path = Path("/media/facebook-photos")

    # Physical filename: only date/time + Facebook ID (no post text,
    # which instead goes in the description/.nfo — see nfo.py).
    # Underscore as separator, never spaces.
    filename_template: str = "{date}_{id}"

    # Video/reel: organized as seasons (year) of a TV show per profile,
    # for a chronological Jellyfin view instead of a movie grid.
    folder_template_video: str = "{profile}/Stagione {season}"
    # Photos: folder per profile inside the DEDICATED photo root
    # (photo_media_root), grouped by POST (publish date-time + post ID)
    # — so multiple photos from the same post (album) end up in the same
    # folder instead of one folder each.
    folder_template_photo: str = "{profile}/{date}_{post_id}"
    # Photo filename: the individual photo's own Facebook ID (may get a
    # "-2", "-3"... suffix when multiple photos from the same post would
    # otherwise share the same ID) — no more of the unreadable filename
    # derived from the Facebook CDN URL.
    filename_template_photo: str = "{id}"

    # Includes the time in addition to the date (needed for the
    # filename, which is now just date-time + id). Uses dashes, not
    # colons: colons aren't valid in filenames on many filesystems.
    date_format: str = "%Y-%m-%d-%H-%M"

    generate_nfo: bool = True

    # Web UI authentication (HTTP Basic). If admin_password is empty,
    # the app stays open without login (unchanged default behavior).
    admin_username: str = "admin"
    admin_password: str = ""

    # Interface language (code, e.g. "it", "en", "zh-CN"); persisted like
    # the other settings. Default is English as requested.
    ui_language: str = "en"

    # In-memory log detail level (0=errors only, 1=main events,
    # 2=technical detail, 3=everything including raw yt-dlp/gallery-dl
    # output). Persisted like the other settings.
    log_level: int = 1

    # Web UI color theme: "dark" (default, Facebook-style) or "light".
    theme: str = "dark"

    # Best-effort translation of the post description into ui_language
    # (uses Google Translate's free endpoint, no API key — see
    # translate.py for the caveats). Off by default: it's an extra
    # network call per item and depends on an unofficial endpoint.
    translate_description: bool = False

    @property
    def db_path(self) -> Path:
        return self.config_dir / "fb-downloader.db"

    @property
    def cookies_path(self) -> Path:
        return self.config_dir / "facebook_cookies.txt"


settings = Settings()
settings.config_dir.mkdir(parents=True, exist_ok=True)
settings.media_root.mkdir(parents=True, exist_ok=True)
settings.photo_media_root.mkdir(parents=True, exist_ok=True)
