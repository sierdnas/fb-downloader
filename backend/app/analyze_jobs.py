"""
Background analysis job: analyzing a profile/page with many posts
requires yt-dlp to query every single item, which can take minutes.
Previously /api/analyze was synchronous and blocked the HTTP request
for all that time (risk of browser timeout).

Now: POST /api/analyze starts the job and returns IMMEDIATELY with a
job_id; the UI polls GET /api/analyze/{job_id} until the status is
"done" or "error", exactly like already done for the download queue.

Jobs live in memory only (no persistence needed: they're short-lived
and specific to the current analysis session) and are cleaned up after
a while so they don't accumulate forever in a long-running process.
"""
import threading
import time
import uuid
from datetime import date

from . import downloader

_jobs: dict[str, dict] = {}
_lock = threading.Lock()

_JOB_TTL_SECONDS = 1800  # 30 minutes: beyond that, a completed job is discarded


def start_job(url: str, date_from: "date | None", date_to: "date | None") -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "status": "running",
            "url": url,
            "raw_items": None,
            "error": None,
            "created_at": time.time(),
        }
        _purge_old(_jobs)

    t = threading.Thread(target=_run_job, args=(job_id, url, date_from, date_to), daemon=True)
    t.start()
    return job_id


def get_job(job_id: str) -> "dict | None":
    with _lock:
        return _jobs.get(job_id)


def _run_job(job_id: str, url: str, date_from: "date | None", date_to: "date | None") -> None:
    try:
        raw_items = downloader.analyze_url(url, date_from=date_from, date_to=date_to)
        with _lock:
            job = _jobs.get(job_id)
            if job is not None:
                job["status"] = "done"
                job["raw_items"] = raw_items
    except Exception as exc:  # noqa: BLE001 - any error becomes a message for the UI
        with _lock:
            job = _jobs.get(job_id)
            if job is not None:
                job["status"] = "error"
                job["error"] = str(exc)


def _purge_old(jobs: dict) -> None:
    """Called under lock. Removes jobs older than _JOB_TTL_SECONDS."""
    now = time.time()
    expired = [jid for jid, j in jobs.items() if now - j["created_at"] > _JOB_TTL_SECONDS]
    for jid in expired:
        del jobs[jid]
