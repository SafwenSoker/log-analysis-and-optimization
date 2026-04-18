"""
Model management routes:
  POST /api/model/train         — train (or retrain) the ML model
  GET  /api/model/metrics       — return training metrics + CV results
  GET  /api/model/status        — is model trained? which model? accuracy?
  POST /api/model/flaky/compute — recompute flaky test analysis
  GET  /api/model/flaky         — list flaky/failing scenarios
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException

from src.model import predictor
from src.model.flaky_detector import get_flaky_summary
from src.storage import database as db

router = APIRouter(prefix="/api/model", tags=["model"])


def _train_task():
    import logging
    from src.model.trainer import train
    logging.basicConfig(level=logging.INFO)
    try:
        train()
        predictor.reload()
    except Exception as e:
        logging.error(f"Training failed: {e}")


@router.post("/train")
def train_model(background_tasks: BackgroundTasks):
    """Trigger model training in the background."""
    background_tasks.add_task(_train_task)
    return {"status": "training_started", "message": "Training running in background — check /api/model/status"}


@router.post("/train/sync")
def train_model_sync():
    """Train synchronously — blocks until complete. Returns metrics."""
    from src.model.trainer import train
    import logging
    logging.basicConfig(level=logging.INFO)
    try:
        metrics = train()
        predictor.reload()
        return metrics
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metrics")
def get_metrics():
    metrics = predictor.get_metrics()
    if not metrics:
        raise HTTPException(
            status_code=404,
            detail="No trained model found. POST /api/model/train first."
        )
    return metrics


@router.get("/status")
def get_status():
    trained = predictor.is_trained()
    if not trained:
        return {"trained": False, "model": None}
    metrics = predictor.get_metrics()
    if not metrics:
        return {"trained": True, "model": None}
    best = metrics.get("best_model", "unknown")
    cv   = metrics.get("cv_results", {}).get(best, {})
    return {
        "trained":          True,
        "model":            best,
        "trained_at":       metrics.get("trained_at"),
        "n_samples":        metrics.get("n_samples"),
        "n_classes":        metrics.get("n_classes"),
        "accuracy":         round(cv.get("accuracy_mean", 0), 4),
        "f1_weighted":      round(cv.get("f1_weighted_mean", 0), 4),
        "f1_macro":         round(cv.get("f1_macro_mean", 0), 4),
    }


@router.post("/flaky/compute")
def compute_flaky(background_tasks: BackgroundTasks):
    """Recompute flaky test analysis across all ingested logs."""
    def _task():
        summary = get_flaky_summary()
        all_scenarios = (
            summary["flaky_scenarios"] +
            summary["failing_scenarios"]
        )
        db.save_flaky_results(all_scenarios)

    background_tasks.add_task(_task)
    return {"status": "computing", "message": "Flaky analysis running in background"}


@router.post("/flaky/compute/sync")
def compute_flaky_sync():
    """Compute flaky analysis synchronously. Returns summary."""
    summary = get_flaky_summary()
    all_scenarios = summary["flaky_scenarios"] + summary["failing_scenarios"]
    db.save_flaky_results(all_scenarios)
    return summary


@router.get("/flaky")
def list_flaky(status: str | None = None, limit: int = 100):
    """List flaky / consistently-failing scenarios from the last computed run."""
    rows = db.list_flaky_tests(status=status, limit=limit)
    total_flaky = sum(1 for r in rows if r["status"] == "FLAKY")
    return {
        "total":  len(rows),
        "flaky":  total_flaky,
        "scenarios": rows,
    }
