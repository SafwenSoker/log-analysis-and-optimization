"""
Training pipeline.

Steps:
  1. Load all log files from data/logs/
  2. Parse → extract features
  3. Load labels from data/labels.csv (manual annotations).
     Falls back to rule-based classifier for logs not in the CSV.
  4. Drop classes with fewer than MIN_SAMPLES_PER_CLASS samples.
  5. Build a combined feature matrix (structured + TF-IDF text)
  6. Hold out 20% as a truly unseen test set (stratified).
  7. Train & compare 4 classifiers with stratified k-fold CV on train set.
  8. Select best model by weighted F1, fit on full train set.
  9. Evaluate on held-out test set, persist pipeline + metrics.
"""

import csv
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
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
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

MODEL_PATH   = Path("data/model.joblib")
METRICS_PATH = Path("data/model_metrics.json")
LABELS_PATH  = Path("data/labels.csv")
MIN_SAMPLES_PER_CLASS = 5
VALIDATION_SIZE = 25  # logs held out entirely from training and model selection

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
        eval_metric="mlogloss", random_state=42, n_jobs=-1,
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


def _load_manual_labels() -> dict[str, str]:
    """Load filename → label mapping from labels.csv if it exists."""
    if not LABELS_PATH.exists():
        return {}
    mapping = {}
    with open(LABELS_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mapping[row["filename"]] = row["label"]
    logger.info(f"Loaded {len(mapping)} manual labels from {LABELS_PATH}")
    return mapping


def _load_dataset(logs_dir: Path) -> tuple[list, list[str], list[str]]:
    """
    Returns:
      rows       — list of (structured_array, text_str)
      labels     — list of error category strings (target)
      filenames  — list of log filenames (for reporting)

    Label priority: manual labels.csv > rule-based classifier fallback.
    Classes with fewer than MIN_SAMPLES_PER_CLASS samples are dropped.
    """
    manual_labels = _load_manual_labels()

    rows, labels, filenames = [], [], []
    seen = set()
    all_files = (
        sorted(logs_dir.glob("*.log"))
        + sorted(logs_dir.glob("*.log.txt"))
        + sorted(logs_dir.glob("*.txt"))
    )
    log_files = [p for p in all_files if p.resolve() not in seen and not seen.add(p.resolve())]

    for path in log_files:
        try:
            build = parse_log_file(path)
        except Exception as e:
            logger.warning(f"Skipping {path.name}: {e}")
            continue

        if path.name in manual_labels:
            label = manual_labels[path.name]
        else:
            classification = classify(build)
            label = "SUCCESS" if build.status == BuildStatus.SUCCESS and not build.errors \
                else classification.primary_category.value

        structured, text = build_to_row(build)
        rows.append((structured, text))
        labels.append(label)
        filenames.append(path.name)

    # Drop classes that have too few samples for stratified CV
    from collections import Counter
    counts = Counter(labels)
    valid_classes = {cls for cls, cnt in counts.items() if cnt >= MIN_SAMPLES_PER_CLASS}
    dropped = {cls: cnt for cls, cnt in counts.items() if cls not in valid_classes}
    if dropped:
        logger.warning(f"Dropping classes with < {MIN_SAMPLES_PER_CLASS} samples: {dropped}")
        filtered = [(r, l, f) for r, l, f in zip(rows, labels, filenames) if l in valid_classes]
        rows, labels, filenames = zip(*filtered) if filtered else ([], [], [])
        rows, labels, filenames = list(rows), list(labels), list(filenames)

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

    # ── Step 1: hold out VALIDATION_SIZE logs — never touched during training ──
    rows_traintest, rows_val, y_traintest, y_val = train_test_split(
        rows, y, test_size=VALIDATION_SIZE, stratify=y, random_state=42
    )
    logger.info(
        f"Train+Test pool: {len(rows_traintest)} samples | "
        f"Validation (held-out): {len(rows_val)} samples"
    )

    # ── Step 2: split train+test pool into 80/20 for model selection ──────────
    rows_train, rows_test, y_train, y_test = train_test_split(
        rows_traintest, y_traintest, test_size=0.2, stratify=y_traintest, random_state=42
    )
    logger.info(f"Train: {len(rows_train)} | Test: {len(rows_test)}")

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    # ── Step 3: cross-validate all candidates on train set only ───────────────
    cv_results = {}
    for name, clf in CANDIDATE_MODELS.items():
        logger.info(f"Cross-validating {name} ...")
        pipeline = _build_pipeline(clf)
        scores = cross_validate(
            pipeline, rows_train, y_train, cv=cv,
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

    # ── Step 4: pick best model, fit on full train+test pool ──────────────────
    best_name = max(cv_results, key=lambda n: cv_results[n]["f1_weighted_mean"])
    logger.info(f"Best model: {best_name}")

    best_pipeline = _build_pipeline(CANDIDATE_MODELS[best_name])
    best_pipeline.fit(rows_traintest, y_traintest)

    # ── Step 5: evaluate on held-out test fold (model selection check) ────────
    all_labels = list(range(len(le.classes_)))

    y_pred_test = best_pipeline.predict(rows_test)
    test_report = classification_report(
        y_test, y_pred_test,
        labels=all_labels,
        target_names=le.classes_,
        output_dict=True,
        zero_division=0,
    )

    # ── Step 6: final honest evaluation on the 25 validation logs ─────────────
    y_pred_val = best_pipeline.predict(rows_val)
    val_report = classification_report(
        y_val, y_pred_val,
        labels=all_labels,
        target_names=le.classes_,
        output_dict=True,
        zero_division=0,
    )
    val_conf_matrix = confusion_matrix(y_val, y_pred_val, labels=all_labels).tolist()

    logger.info(
        f"Validation set (n={len(rows_val)}): "
        f"accuracy={val_report['accuracy']:.3f} "
        f"f1_weighted={val_report['weighted avg']['f1-score']:.3f}"
    )

    # Feature importance (Random Forest / XGBoost only)
    feature_importance = None
    clf_step = best_pipeline.named_steps["clf"]
    if hasattr(clf_step, "feature_importances_"):
        feature_importance = clf_step.feature_importances_.tolist()

    # ── Persist ──────────────────────────────────────────────────────────────
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": best_pipeline, "label_encoder": le}, MODEL_PATH)

    metrics = {
        "trained_at":       datetime.now(timezone.utc).isoformat(),
        "n_samples":        len(rows),
        "n_train_test":     len(rows_traintest),
        "n_validation":     len(rows_val),
        "n_classes":        int(len(le.classes_)),
        "classes":          le.classes_.tolist(),
        "best_model":       best_name,
        "cv_results":       cv_results,
        "test_report":      test_report,
        "validation_report":      val_report,
        "validation_confusion_matrix": val_conf_matrix,
        "feature_importance":    feature_importance,
        "label_distribution":    {
            cls: int(np.sum(y == i)) for i, cls in enumerate(le.classes_)
        },
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2))
    logger.info(f"Model saved to {MODEL_PATH}")
    return metrics
