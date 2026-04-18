"""
Feature extraction for ML training and inference.

Two feature groups combined into a single feature vector:
  1. Structured features  — numerical/categorical fields from ParsedBuild
  2. Text features        — TF-IDF on the most diagnostic log sections
"""

import re
import numpy as np
from pathlib import Path

from src.parser.models import JobType, ParsedBuild

# ── Job type encoding ────────────────────────────────────────────────────────
JOB_TYPE_INDEX = {
    JobType.FCTU_TRAIN1:     0,
    JobType.FCTU_TRAIN2:     1,
    JobType.PROD_SERIALIZER: 2,
    JobType.PROD_ATIJ:       3,
    JobType.UNKNOWN:         4,
}

# ── Keyword flags ────────────────────────────────────────────────────────────
_KEYWORD_PATTERNS = [
    ("kw_connection_refused", re.compile(r"ERR_CONNECTION_REFUSED|est injoignable", re.I)),
    ("kw_no_tests",           re.compile(r"No tests were executed|Tests run: 0", re.I)),
    ("kw_aborted",            re.compile(r"Build was aborted|Aborted by", re.I)),
    ("kw_step_failed",        re.compile(r"STEP .+? FAILED", re.I)),
    ("kw_sql_error",          re.compile(r"SQLException|ORA-\d+", re.I)),
    ("kw_compile_error",      re.compile(r"COMPILATION ERROR", re.I)),
    ("kw_git_error",          re.compile(r"ERROR.*git|Repository .* not found", re.I)),
    ("kw_timeout",            re.compile(r"timed? ?out", re.I)),
    ("kw_cucumber_fail",      re.compile(r"<<< FAILURE!", re.I)),
    ("kw_build_success",      re.compile(r"BUILD SUCCESS", re.I)),
    ("kw_build_failure",      re.compile(r"BUILD FAILURE", re.I)),
    ("kw_unstable",           re.compile(r"Finished: UNSTABLE", re.I)),
]

KEYWORD_NAMES = [name for name, _ in _KEYWORD_PATTERNS]
N_KEYWORDS    = len(KEYWORD_NAMES)
N_JOB_TYPES   = len(JOB_TYPE_INDEX)
N_STRUCTURED  = N_JOB_TYPES + N_KEYWORDS + 6   # 6 numeric fields


def extract_structured(build: ParsedBuild) -> np.ndarray:
    """
    Returns a 1-D numpy array of structured features.
    Layout:
      [0..4]   job_type one-hot  (5 dims)
      [5..16]  keyword flags     (12 dims)
      [17]     tests_run         (normalised / 100)
      [18]     failure_rate      (failures / (run+1))
      [19]     error_rate        (errors   / (run+1))
      [20]     skipped_rate      (skipped  / (run+1))
      [21]     has_duration      (0/1)
      [22]     log_line_count    (normalised / 1000)
    """
    vec = np.zeros(N_STRUCTURED, dtype=np.float32)

    # Job type one-hot
    idx = JOB_TYPE_INDEX.get(build.job_type, JOB_TYPE_INDEX[JobType.UNKNOWN])
    vec[idx] = 1.0

    # Keyword flags
    raw = build.raw_log
    for i, (_, pattern) in enumerate(_KEYWORD_PATTERNS):
        vec[N_JOB_TYPES + i] = 1.0 if pattern.search(raw) else 0.0

    # Numeric fields (normalised)
    run      = build.test_results.tests_run
    failures = build.test_results.failures
    errors   = build.test_results.errors
    skipped  = build.test_results.skipped
    denom    = run + 1

    offset = N_JOB_TYPES + N_KEYWORDS
    vec[offset]     = min(run / 100.0, 1.0)
    vec[offset + 1] = failures / denom
    vec[offset + 2] = errors   / denom
    vec[offset + 3] = skipped  / denom
    vec[offset + 4] = 1.0 if build.duration_seconds else 0.0
    vec[offset + 5] = min(build.log_line_count / 1000.0, 1.0)

    return vec


def extract_text_section(build: ParsedBuild, tail_lines: int = 80) -> str:
    """
    Returns the most diagnostic text portion of the log:
      - All [ERROR] and <<< FAILURE lines
      - The last N lines (where final status + stack traces appear)
    """
    lines = build.raw_log.splitlines()

    error_lines = [
        l for l in lines
        if re.search(r"\[ERROR\]|<<< FAILURE|FAILED|Exception|Error:", l)
    ]

    tail = lines[-tail_lines:]
    combined = error_lines + tail
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for l in combined:
        key = l.strip()
        if key not in seen:
            seen.add(key)
            deduped.append(l)

    return " ".join(deduped)


def build_to_row(build: ParsedBuild) -> tuple[np.ndarray, str]:
    """
    Returns (structured_features, text_section) for one build.
    Used by both trainer and predictor.
    """
    return extract_structured(build), extract_text_section(build)
