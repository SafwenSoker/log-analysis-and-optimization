"""
Training pipeline.

Steps:
  1. Load all log files from data/logs/
  2. Parse → extract features → auto-label via rule-based classifier
  3. Build a combined feature matrix (structured + TF-IDF text)
  4. Train & compare 4 classifiers with stratified k-fold CV
  5. Select best model by weighted F1
  6. Persist pipeline with joblib + save metrics to DB
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import StratifiedKFold, cross_validate
from sklearn.pipeline import Pipeline, FeatureUnion
from sklearn.preprocessing import LabelEncoder
from sklearn.svm import LinearSVC
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.base import BaseEstimator, TransformerMixin
from xgboost import XGBClassifier

from src.classifier.error_classifier import classify
from src.model.features import build_to_row, extract_structured, extract_text_section
from src.parser.log_parser import parse_log_file
from src.parser.models import BuildStatus

logger = logging.getLogger(__name__)

MODEL_PATH  = Path("data/model.joblib")
METRICS_PATH = Path("data/model_metrics.json")

CANDIDATE_MODELS = {
    "LogisticRegression": LogisticRegression(
        max_iter=1000, class_weight="balanced", C=1.0, random_state=42
    ),
    "RandomForest": RandomForestClassifier(
        n_estimators=200, class_weight="balanced", random_state=42, n_jobs=-1
    ),
    "LinearSVC": LinearSVC(
        max_iter=2000, class_weight="balanced", C=1.0, random_state=42
    ),
    "XGBoost": XGBClassifier(
        n_estimators=200, learning_rate=0.1, max_depth=6,
        use_label_encoder=False, eval_metric="mlogloss",
        random_state=42, n_jobs=-1,
    ),
}


# ── Custom transformers for FeatureUnion ─────────────────────────────────────

class StructuredExtractor(BaseEstimator, TransformerMixin):
    """Extracts pre-computed structured feature arrays from raw log text."""
    def fit(self, X, y=None):
        return self

    def transform(self, X):
        # X is a list of (structured_array, text_str) tuples
        return np.vstack([row[0] for row in X])


class TextExtractor(BaseEstimator, TransformerMixin):
    """Extracts text strings from (structured, text) tuples for TF-IDF."""
    def fit(self, X, y=None):
        return self

    def transform(self, X):
        return [row[1] for row in X]


def _load_dataset(logs_dir: Path) -> tuple[list, list[str], list[str]]:
    """
    Returns:
      rows       — list of (structured_array, text_str)
      labels     — list of error category strings (target)
      filenames  — list of log filenames (for reporting)
    """
    rows, labels, filenames = [], [], []
    log_files = sorted(logs_dir.glob("*.log")) + sorted(logs_dir.glob("*.log.txt")) + sorted(logs_dir.glob("*.txt"))

    for path in log_files:
        try:
            build = parse_log_file(path)
        except Exception as e:
            logger.warning(f"Skipping {path.name}: {e}")
            continue

        classification = classify(build)

        # Skip builds with no useful signal (pure SUCCESS with no errors)
        if build.status == BuildStatus.SUCCESS and not build.errors:
            label = "SUCCESS"
        else:
            label = classification.primary_category.value

        structured, text = build_to_row(build)
        rows.append((structured, text))
        labels.append(label)
        filenames.append(path.name)

    return rows, labels, filenames


def _build_pipeline(model) -> Pipeline:
    feature_union = FeatureUnion([
        ("structured", StructuredExtractor()),
        ("tfidf", Pipeline([
            ("text", TextExtractor()),
            ("tfidf", TfidfVectorizer(
                max_features=800,
                ngram_range=(1, 2),
                sublinear_tf=True,
                min_df=2,
            )),
        ])),
    ])
    return Pipeline([
        ("features", feature_union),
        ("clf", model),
    ])


def train(logs_dir: str | Path = "data/logs") -> dict:
    logs_dir = Path(logs_dir)
    logger.info(f"Loading logs from {logs_dir} ...")

    rows, labels, filenames = _load_dataset(logs_dir)
    if len(rows) < 10:
        raise ValueError(f"Only {len(rows)} usable logs found — need at least 10.")

    logger.info(f"Dataset: {len(rows)} samples, {len(set(labels))} classes")

    le = LabelEncoder()
    y  = le.fit_transform(labels)

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    # ── Compare all candidate models ─────────────────────────────────────────
    cv_results = {}
    for name, clf in CANDIDATE_MODELS.items():
        logger.info(f"Cross-validating {name} ...")
        pipeline = _build_pipeline(clf)
        scores = cross_validate(
            pipeline, rows, y, cv=cv,
            scoring=["accuracy", "f1_weighted", "f1_macro"],
            return_train_score=False,
        )
        cv_results[name] = {
            "accuracy_mean":    float(np.mean(scores["test_accuracy"])),
            "accuracy_std":     float(np.std(scores["test_accuracy"])),
            "f1_weighted_mean": float(np.mean(scores["test_f1_weighted"])),
            "f1_weighted_std":  float(np.std(scores["test_f1_weighted"])),
            "f1_macro_mean":    float(np.mean(scores["test_f1_macro"])),
            "f1_macro_std":     float(np.std(scores["test_f1_macro"])),
        }
        logger.info(
            f"  {name}: acc={cv_results[name]['accuracy_mean']:.3f} "
            f"f1_w={cv_results[name]['f1_weighted_mean']:.3f}"
        )

    # ── Pick best model by weighted F1 ───────────────────────────────────────
    best_name = max(cv_results, key=lambda n: cv_results[n]["f1_weighted_mean"])
    logger.info(f"Best model: {best_name}")

    # ── Final fit on full dataset ────────────────────────────────────────────
    best_pipeline = _build_pipeline(CANDIDATE_MODELS[best_name])
    best_pipeline.fit(rows, y)

    # ── Held-out metrics (last fold) ─────────────────────────────────────────
    train_idx, test_idx = list(cv.split(rows, y))[-1]
    X_test = [rows[i] for i in test_idx]
    y_test = y[test_idx]
    y_pred = best_pipeline.predict(X_test)

    report = classification_report(
        y_test, y_pred,
        target_names=le.classes_,
        output_dict=True,
        zero_division=0,
    )
    conf_matrix = confusion_matrix(y_test, y_pred).tolist()

    # Feature importance (Random Forest / XGBoost only)
    feature_importance = None
    clf_step = best_pipeline.named_steps["clf"]
    if hasattr(clf_step, "feature_importances_"):
        fi = clf_step.feature_importances_
        feature_importance = fi.tolist()

    # ── Persist ──────────────────────────────────────────────────────────────
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": best_pipeline, "label_encoder": le}, MODEL_PATH)

    metrics = {
        "trained_at":      datetime.now(timezone.utc).isoformat(),
        "n_samples":       len(rows),
        "n_classes":       int(len(le.classes_)),
        "classes":         le.classes_.tolist(),
        "best_model":      best_name,
        "cv_results":      cv_results,
        "classification_report": report,
        "confusion_matrix":      conf_matrix,
        "feature_importance":    feature_importance,
        "label_distribution":    {
            cls: int(np.sum(y == i)) for i, cls in enumerate(le.classes_)
        },
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    logger.info(f"Model saved to {MODEL_PATH}")
    return metrics
