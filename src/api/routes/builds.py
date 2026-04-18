import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from src.storage import database as db

router = APIRouter(prefix="/api/builds", tags=["builds"])


def _enrich(build: dict) -> dict:
    """Attach analysis data and deserialise JSON fields."""
    build["errors"] = json.loads(build.get("errors_json") or "[]")
    analysis = db.get_analysis_by_build(build["id"])
    if analysis:
        analysis["recommendations"] = json.loads(analysis.get("recommendations_json") or "[]")
        analysis["all_categories"] = json.loads(analysis.get("all_categories_json") or "[]")
        analysis["evidence"] = json.loads(analysis.get("evidence_json") or "[]")
        build["analysis"] = analysis
    else:
        build["analysis"] = None
    return build


@router.get("")
def list_builds(
    job_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    rows = db.list_builds(job_type=job_type, status=status, limit=limit, offset=offset)
    total = db.count_builds(job_type=job_type, status=status)
    for row in rows:
        row["errors"] = json.loads(row.get("errors_json") or "[]")
        row.pop("errors_json", None)
    return {"total": total, "builds": rows}


@router.get("/stats")
def get_stats():
    return db.get_stats()


@router.get("/{build_id}")
def get_build(build_id: int):
    build = db.get_build_by_id(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
    build.pop("errors_json", None)
    return _enrich(build)
