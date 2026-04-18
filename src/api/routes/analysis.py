import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.model import predictor
from src.parser import log_parser
from src.storage import database as db

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

LOGS_DIR = Path("data/logs")


def _run_analysis(build_id: int, log_path: Path) -> dict:
    """Parse → ML predict → persist. Returns analysis dict."""
    parsed     = log_parser.parse_log_file(log_path)
    prediction = predictor.predict(parsed)

    analysis_data = {
        "build_id":             build_id,
        "predicted_category":   prediction.predicted_category,
        "all_categories_json":  json.dumps([prediction.predicted_category]),
        "severity":             prediction.severity,
        "label":                prediction.label,
        "recommendations_json": json.dumps(prediction.recommendations),
        "confidence_score":     prediction.confidence_score,
        "probabilities_json":   json.dumps(prediction.probabilities),
        "model_used":           prediction.model_used,
    }
    db.save_analysis(analysis_data)
    db.mark_analysis_done(build_id)
    return analysis_data


@router.post("/{build_id}")
def trigger_analysis(build_id: int, background_tasks: BackgroundTasks):
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
    build = db.get_build_by_id(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
    log_path = LOGS_DIR / build["filename"]
    if not log_path.exists():
        raise HTTPException(status_code=404, detail=f"Log file not found: {build['filename']}")
    result = _run_analysis(build_id, log_path)
    result["recommendations"] = json.loads(result.pop("recommendations_json", "[]"))
    result["probabilities"]   = json.loads(result.pop("probabilities_json", "{}"))
    result.pop("all_categories_json", None)
    return result


@router.get("/{build_id}")
def get_analysis(build_id: int):
    analysis = db.get_analysis_by_build(build_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis found for this build")
    analysis["recommendations"] = json.loads(analysis.get("recommendations_json") or "[]")
    analysis["probabilities"]   = json.loads(analysis.get("probabilities_json") or "{}")
    return analysis
