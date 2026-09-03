import re
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from .auth_middleware import BasicAuthMiddleware
from .db import engine, init_db
from .queue_worker import start_worker
from .routers import analyze, auth, download, history, logs_router, queue_router
from .routers import settings_router

app = FastAPI(title="fb-downloader")
app.add_middleware(BasicAuthMiddleware)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    with Session(engine) as session:
        settings_router.load_persisted_settings(session)
    start_worker()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


_URL_RE = re.compile(r"https?://\S+")


@app.get("/share-target")
def share_target(title: str = "", text: str = "", url: str = "") -> RedirectResponse:
    """Receives content shared from other Android apps (e.g. the "Share"
    button in the Facebook app), once installed as a PWA with the
    share_target declared in manifest.json. Different apps put the
    actual link in different fields (some in "url", many just dump it
    inside "text" alongside other text) — tries "url" first, then
    extracts the first http(s) link found in "text", then falls back to
    the raw text/title as a last resort. Redirects to the main page with
    the link pre-filled in the URL box (see app.js, which reads the
    "shared_url" query parameter on load)."""
    candidate = url.strip()
    if not candidate:
        match = _URL_RE.search(text)
        if match:
            candidate = match.group(0)
    if not candidate:
        candidate = (text or title).strip()

    return RedirectResponse(url=f"/?shared_url={quote(candidate)}")


app.include_router(auth.router)
app.include_router(analyze.router)
app.include_router(download.router)
app.include_router(queue_router.router)
app.include_router(settings_router.router)
app.include_router(history.router)
app.include_router(logs_router.router)

# Static web UI (index.html + assets), mounted last so /api/* routes take priority
app.mount("/", StaticFiles(directory="static", html=True), name="static")
