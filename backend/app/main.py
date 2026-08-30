from fastapi import FastAPI
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


app.include_router(auth.router)
app.include_router(analyze.router)
app.include_router(download.router)
app.include_router(queue_router.router)
app.include_router(settings_router.router)
app.include_router(history.router)
app.include_router(logs_router.router)

# Static web UI (index.html + assets), mounted last so /api/* routes take priority
app.mount("/", StaticFiles(directory="static", html=True), name="static")
