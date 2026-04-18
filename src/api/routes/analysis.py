import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.agent import claude_agent
from src.classifier import error_classifier
from src.parser import log_parser
from src.storage import database as db

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

LOGS_DIR = Path("data/logs")


def _run_analysis(build_id: int, log_path: Path) -> dict:
    """Parse → classify → agent analyse → persist. Returns analysis dict."""
    parsed = log_parser.parse_log_file(log_path)
    classification = error_classifier.classify(parsed)
    agent_result = claude_agent.analyse_build(parsed, classification)

    analysis_data = {
        "build_id": build_id,
        "primary_category": classification.primary_category.value,
        "all_categories_json": json.dumps([c.value for c in classification.all_categories]),
        "severity": classification.severity.value,
        "label": classification.label,
        "recommendations_json": json.dumps(classification.recommendations),
        "root_cause": agent_result.get("root_cause", ""),
        "explanation": agent_result.get("explanation", ""),
        "confidence": agent_result.get("confidence", "LOW"),
        "evidence_json": json.dumps(agent_result.get("evidence", [])),
        "recurring_risk": agent_result.get("recurring_risk", "UNKNOWN"),
        "agent_used": True,
    }
    db.save_analysis(analysis_data)
    db.mark_analysis_done(build_id)
    return analysis_data


@router.post("/{build_id}")
def trigger_analysis(build_id: int, background_tasks: BackgroundTasks):
    """Trigger async root-cause analysis for a specific build."""
    build = db.get_build_by_id(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    log_path = LOGS_DIR / build["filename"]
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {build['filename']}")

    background_tasks.add_task(_run_analysis, build_id, log_path)
    return {"status": "queued", "build_id": build_id}


@router.post("/{build_id}/sync")
def trigger_analysis_sync(build_id: int):
    """Synchronous analysis — returns result immediately (blocks until done)."""
    build = db.get_build_by_id(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")

    log_path = LOGS_DIR / build["filename"]
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {build['filename']}")

    result = _run_analysis(build_id, log_path)
    result["recommendations"] = json.loads(result.pop("recommendations_json", "[]"))
    result["all_categories"] = json.loads(result.pop("all_categories_json", "[]"))
    result["evidence"] = json.loads(result.pop("evidence_json", "[]"))
    return result


@router.get("/{build_id}")
def get_analysis(build_id: int):
    analysis = db.get_analysis_by_build(build_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis found for this build")
    analysis["recommendations"] = json.loads(analysis.get("recommendations_json") or "[]")
    analysis["all_categories"] = json.loads(analysis.get("all_categories_json") or "[]")
    analysis["evidence"] = json.loads(analysis.get("evidence_json") or "[]")
    return analysis
