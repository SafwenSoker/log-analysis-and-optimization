import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile

from src.api.routes.analysis import _run_analysis
from src.api.routes.jenkins import _ingest_file
from src.parser import log_parser

router = APIRouter(prefix="/api/upload", tags=["upload"])

LOGS_DIR = Path("data/logs")


@router.post("")
async def upload_log(file: UploadFile, background_tasks: BackgroundTasks, analyse: bool = True):
    """
    Upload a Jenkins log file for ingestion and optional analysis.
    Accepts any .txt or .log file.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    content = await file.read()
    try:
        text = content.decode("utf-8", errors="replace")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not decode file: {e}")

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / file.filename
    log_path.write_text(text, encoding="utf-8")

    build_id = _ingest_file(log_path)
    if build_id is None:
        raise HTTPException(status_code=422, detail="Could not parse log file")

    if analyse:
        background_tasks.add_task(_run_analysis, build_id, log_path)

    return {
        "status": "ingested",
        "build_id": build_id,
        "filename": file.filename,
        "analysis_queued": analyse,
    }
