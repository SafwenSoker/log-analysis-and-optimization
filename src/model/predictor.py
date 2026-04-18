"""
Inference: load the trained pipeline and predict on a new ParsedBuild.
Falls back to rule-based classification if the model is not yet trained.
"""

import json
from pathlib import Path

import joblib
import numpy as np

from src.classifier.error_classifier import classify, ClassificationResult
from src.model.features import build_to_row
from src.parser.models import ParsedBuild, ErrorCategory, Severity

MODEL_PATH   = Path("data/model.joblib")
METRICS_PATH = Path("data/model_metrics.json")

_cache: dict = {}   # in-memory cache so we don't reload from disk every request


def _load() -> dict | None:
    if "bundle" in _cache:
        return _cache["bundle"]
    if not MODEL_PATH.exists():
        return None
    bundle = joblib.load(MODEL_PATH)
    _cache["bundle"] = bundle
    return bundle


def reload():
    """Force-reload after a new training run."""
    _cache.clear()


def is_trained() -> bool:
    return MODEL_PATH.exists()


def get_metrics() -> dict | None:
    if METRICS_PATH.exists():
        return json.loads(METRICS_PATH.read_text())
    return None


class PredictionResult:
    __slots__ = (
        "predicted_category", "confidence_score", "probabilities",
        "severity", "label", "recommendations", "model_used",
    )

    def __init__(self, predicted_category, confidence_score, probabilities,
                 severity, label, recommendations, model_used):
        self.predicted_category = predicted_category
        self.confidence_score   = confidence_score
        self.probabilities      = probabilities
        self.severity           = severity
        self.label              = label
        self.recommendations    = recommendations
        self.model_used         = model_used

    def to_dict(self) -> dict:
        return {
            "predicted_category": self.predicted_category,
            "confidence_score":   round(self.confidence_score, 4),
            "probabilities":      {k: round(v, 4) for k, v in self.probabilities.items()},
            "severity":           self.severity,
            "label":              self.label,
            "recommendations":    self.recommendations,
            "model_used":         self.model_used,
        }


# Severity + recommendation maps (reused from classifier)
from src.classifier.error_classifier import (
    _SEVERITY_MAP, _CATEGORY_LABELS, _RECOMMENDATIONS
)


def predict(build: ParsedBuild) -> PredictionResult:
    """
    Predict the error category for a parsed build.
    Uses the trained ML model when available, otherwise falls back to
    rule-based classification.
    """
    bundle = _load()

    if bundle is None:
        # Fallback: rule-based
        rule = classify(build)
        return PredictionResult(
            predicted_category=rule.primary_category.value,
            confidence_score=1.0,
            probabilities={rule.primary_category.value: 1.0},
            severity=rule.severity.value,
            label=rule.label,
            recommendations=rule.recommendations,
            model_used="rule-based",
        )

    pipeline = bundle["pipeline"]
    le       = bundle["label_encoder"]

    row = [build_to_row(build)]   # list of one (structured, text) tuple

    # Predict class
    y_pred = pipeline.predict(row)[0]
    category_str = le.inverse_transform([y_pred])[0]

    # Probability estimates (not all classifiers support predict_proba)
    probabilities = {}
    if hasattr(pipeline, "predict_proba"):
        try:
            proba = pipeline.predict_proba(row)[0]
            probabilities = {
                le.inverse_transform([i])[0]: float(p)
                for i, p in enumerate(proba)
            }
        except Exception:
            probabilities = {category_str: 1.0}
    else:
        probabilities = {category_str: 1.0}

    confidence = max(probabilities.values()) if probabilities else 1.0

    # Map back to ErrorCategory enum for severity/recommendations
    try:
        cat_enum = ErrorCategory(category_str)
    except ValueError:
        cat_enum = ErrorCategory.UNKNOWN

    severity      = _SEVERITY_MAP.get(cat_enum, Severity.MEDIUM).value
    label         = _CATEGORY_LABELS.get(cat_enum, category_str)
    recommendations = _RECOMMENDATIONS.get(cat_enum, _RECOMMENDATIONS[ErrorCategory.UNKNOWN])

    return PredictionResult(
        predicted_category=category_str,
        confidence_score=confidence,
        probabilities=probabilities,
        severity=severity,
        label=label,
        recommendations=recommendations,
        model_used="ml",
    )
