"""
Jenkins integration routes.

1. POST /jenkins/webhook  — receive a build-completed notification from Jenkins
   (configured as a Post-build Action → HTTP Request Plugin in Jenkins)

2. POST /jenkins/ingest   — manually ingest all log files from data/logs/

3. GET  /jenkins/fetch/{job}/{build} — fetch a log directly from Jenkins API
   (requires JENKINS_URL + JENKINS_TOKEN in .env)
"""

import json
from pathlib import Path

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from src.api.routes.analysis import _run_analysis
from src.parser import log_parser
from src.storage import database as db

router = APIRouter(prefix="/jenkins", tags=["jenkins"])

LOGS_DIR = Path("data/logs")


class WebhookPayload(BaseModel):
    job_name: str
    build_number: int
    status: str
    log_url: str | None = None


def _ingest_file(log_path: Path) -> int | None:
    """Parse a log file and persist the build. Returns build_id or None if skipped."""
    existing = db.get_build_by_filename(log_path.name)
    if existing:
        return existing["id"]

    try:
        parsed = log_parser.parse_log_file(log_path)
    except Exception:
        return None

    build_data = {
        "filename": parsed.filename,
        "job_type": parsed.job_type.value,
        "build_number": parsed.build_number,
        "status": parsed.status.value,
        "triggered_by": parsed.triggered_by,
        "upstream_job": parsed.upstream_job,
        "git_commit": parsed.git_commit,
        "git_branch": parsed.git_branch,
        "git_commit_message": parsed.git_commit_message,
        "cucumber_tags": parsed.cucumber_tags,
        "tests_run": parsed.test_results.tests_run,
        "test_failures": parsed.test_results.failures,
        "test_errors": parsed.test_results.errors,
        "test_skipped": parsed.test_results.skipped,
        "duration_seconds": parsed.duration_seconds,
        "finished_at": parsed.finished_at,
        "log_line_count": parsed.log_line_count,
        "errors_json": json.dumps([e.model_dump() for e in parsed.errors]),
        "analysis_done": False,
    }
    return db.upsert_build(build_data)


@router.post("/webhook")
async def jenkins_webhook(payload: WebhookPayload, background_tasks: BackgroundTasks):
    """
    Jenkins calls this endpoint after each build completes.
    Configure in Jenkins → Post-build Actions → HTTP Request:
      URL: http://<host>:8000/jenkins/webhook
      Content-Type: application/json
      Body: {"job_name":"$JOB_NAME","build_number":$BUILD_NUMBER,"status":"$BUILD_STATUS"}
    """
    # If a log URL was provided, fetch and save the log file first
    if payload.log_url:
        log_filename = f"{payload.job_name}_build_{payload.build_number}.log.txt"
        log_path = LOGS_DIR / log_filename
        if not log_path.exists():
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    r = await client.get(payload.log_url)
                    r.raise_for_status()
                    log_path.write_text(r.text, encoding="utf-8")
            except Exception as e:
                return {"status": "error", "detail": f"Could not fetch log: {e}"}

        build_id = _ingest_file(log_path)
        if build_id:
            background_tasks.add_task(_run_analysis, build_id, log_path)
            return {"status": "queued", "build_id": build_id}

    return {"status": "received", "detail": "No log_url provided — skipping ingestion"}


@router.post("/ingest")
def ingest_all(background_tasks: BackgroundTasks, analyse: bool = False):
    """
    Ingest every *.log.txt file from data/logs/ into the database.
    Pass ?analyse=true to also trigger Claude analysis for each build.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_files = list(LOGS_DIR.glob("*.log.txt")) + list(LOGS_DIR.glob("*.txt"))
    ingested, skipped = 0, 0

    for path in log_files:
        build_id = _ingest_file(path)
        if build_id is not None:
            ingested += 1
            if analyse:
                background_tasks.add_task(_run_analysis, build_id, path)
        else:
            skipped += 1

    return {
        "ingested": ingested,
        "skipped": skipped,
        "total_files": len(log_files),
        "analysis_queued": analyse,
    }


@router.get("/fetch/{job_name}/{build_number}")
async def fetch_from_jenkins(job_name: str, build_number: int, background_tasks: BackgroundTasks):
    """
    Fetch a build log directly from the Jenkins API and ingest it.
    Requires JENKINS_URL and JENKINS_TOKEN environment variables.
    """
    import os
    jenkins_url = os.getenv("JENKINS_URL")
    jenkins_token = os.getenv("JENKINS_TOKEN")
    jenkins_user = os.getenv("JENKINS_USER", "admin")

    if not jenkins_url:
        raise HTTPException(status_code=503, detail="JENKINS_URL not configured")

    log_url = f"{jenkins_url.rstrip('/')}/job/{job_name}/{build_number}/consoleText"
    log_filename = f"{job_name}build_{build_number}.log.txt"
    log_path = LOGS_DIR / log_filename

    if not log_path.exists():
        auth = (jenkins_user, jenkins_token) if jenkins_token else None
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                r = await client.get(log_url, auth=auth)
                r.raise_for_status()
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_path.write_text(r.text, encoding="utf-8")
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Jenkins API error: {e}")

    build_id = _ingest_file(log_path)
    if build_id is None:
        raise HTTPException(status_code=500, detail="Failed to parse and ingest log")

    background_tasks.add_task(_run_analysis, build_id, log_path)
    return {"status": "queued", "build_id": build_id, "filename": log_filename}
