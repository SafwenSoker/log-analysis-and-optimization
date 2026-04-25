"""
Flaky test detector.

A test scenario is considered FLAKY when, across multiple build executions,
it alternates between PASS and FAIL rather than consistently doing one or the other.

Detection logic per scenario:
  - fail_rate           : failures / total_runs  (0.0 – 1.0)
  - alternation_rate    : number of PASS↔FAIL transitions / (total_runs - 1)
  - A scenario is FLAKY if:
      0.10 < fail_rate < 0.90   AND   alternation_rate >= 0.30
  - A scenario is CONSISTENTLY_FAILING if fail_rate >= 0.90
  - A scenario is CONSISTENTLY_PASSING  if fail_rate <= 0.10

Log format (actual Cucumber output):
  Failed scenarios:
  file:///path/features/fctu/ScenarioName.feature:158 # Scenario description
  ...
  13 Scenarios (3 failed, 10 passed)
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from src.parser.log_parser import parse_log_file
from src.parser.models import BuildStatus, JobType

# Extracts scenario name from "Failed scenarios:" section lines:
# file:///path/features/fctu/Name.feature:158 # Scenario description
_FAIL_SCENARIO_RE = re.compile(r'\.feature:\d+\s+#\s+(.+?)$', re.M)

# Detects whether a "Failed scenarios:" section exists at all
_FAILED_SECTION_RE = re.compile(r'^Failed scenarios:\s*$', re.M)

# Cucumber jobs that produce scenario-level output
_CUCUMBER_JOBS = {JobType.FCTU_TRAIN1, JobType.FCTU_TRAIN2, JobType.PROD_ATIJ}


@dataclass
class ScenarioHistory:
    name: str
    job_type: str
    runs: list[bool] = field(default_factory=list)  # True = passed, False = failed

    @property
    def total_runs(self) -> int:
        return len(self.runs)

    @property
    def fail_rate(self) -> float:
        if not self.runs:
            return 0.0
        return sum(1 for r in self.runs if not r) / len(self.runs)

    @property
    def alternation_rate(self) -> float:
        if len(self.runs) < 2:
            return 0.0
        transitions = sum(1 for a, b in zip(self.runs, self.runs[1:]) if a != b)
        return transitions / (len(self.runs) - 1)

    @property
    def status(self) -> str:
        fr = self.fail_rate
        ar = self.alternation_rate
        if fr <= 0.10:
            return "STABLE_PASSING"
        if fr >= 0.90:
            return "CONSISTENTLY_FAILING"
        if ar >= 0.30:
            return "FLAKY"
        return "MOSTLY_FAILING"

    def to_dict(self) -> dict:
        return {
            "scenario_name":    self.name,
            "job_type":         self.job_type,
            "total_runs":       self.total_runs,
            "fail_count":       sum(1 for r in self.runs if not r),
            "pass_count":       sum(1 for r in self.runs if r),
            "fail_rate":        round(self.fail_rate, 4),
            "alternation_rate": round(self.alternation_rate, 4),
            "status":           self.status,
            "run_history":      ["PASS" if r else "FAIL" for r in self.runs],
        }


def _extract_failing_scenarios(log_text: str) -> set[str]:
    """Extract names of failing Cucumber scenarios from the 'Failed scenarios:' section."""
    if not _FAILED_SECTION_RE.search(log_text):
        return set()
    names = set()
    for m in _FAIL_SCENARIO_RE.finditer(log_text):
        name = m.group(1).strip()
        if len(name) > 3:
            names.add(name[:300])
    return names


def analyse_flakiness(logs_dir: str | Path = "data/logs") -> dict[str, "ScenarioHistory"]:
    """
    Scan all Cucumber log files, build per-scenario run histories,
    and return a dict of '{job_type}::{scenario_name}' → ScenarioHistory.

    Strategy:
      1. First pass: collect failed scenario names per build and all known
         scenario names per job type (union of all failures across all builds).
      2. Second pass: for each build, scenarios in the job's universe that
         did NOT appear in that build's failed list are marked as PASSED.
    """
    logs_dir = Path(logs_dir)
    all_files = (
        sorted(logs_dir.glob("*.log"))
        + sorted(logs_dir.glob("*.log.txt"))
        + sorted(logs_dir.glob("*.txt"))
    )
    seen: set = set()
    log_files = [p for p in all_files if p.resolve() not in seen and not seen.add(p.resolve())]

    # First pass: collect per-build failures and build the universe of scenario names
    build_data: list[tuple[str, set[str], bool]] = []  # (job_type, failed_names, had_cucumber_output)
    universe: dict[str, set[str]] = defaultdict(set)   # job_type -> all known scenario names

    for path in log_files:
        try:
            build = parse_log_file(path)
        except Exception:
            continue

        if build.job_type not in _CUCUMBER_JOBS:
            continue

        raw = build.raw_log or path.read_text(encoding="utf-8", errors="replace")
        failed = _extract_failing_scenarios(raw)
        had_output = bool(_FAILED_SECTION_RE.search(raw)) or build.status == BuildStatus.SUCCESS

        job_type = build.job_type.value
        build_data.append((job_type, failed, had_output))
        for name in failed:
            universe[job_type].add(name)

    # Second pass: build run histories
    histories: dict[str, ScenarioHistory] = {}

    for job_type, failed, had_output in build_data:
        if not had_output:
            continue

        all_known = universe[job_type]
        if not all_known:
            continue

        for name in all_known:
            key = f"{job_type}::{name}"
            if key not in histories:
                histories[key] = ScenarioHistory(name=name, job_type=job_type)
            histories[key].runs.append(name not in failed)  # True = passed

    return histories


def get_flaky_summary(logs_dir: str | Path = "data/logs") -> dict:
    histories = analyse_flakiness(logs_dir)

    flaky, consistently_failing, stable = [], [], []

    for h in histories.values():
        if h.total_runs < 2:
            continue
        s = h.status
        if s == "FLAKY":
            flaky.append(h.to_dict())
        elif s == "CONSISTENTLY_FAILING":
            consistently_failing.append(h.to_dict())
        else:
            stable.append(h.name)

    total = len(flaky) + len(consistently_failing) + len(stable)
    flaky_rate = len(flaky) / total if total > 0 else 0.0

    flaky.sort(key=lambda x: x["alternation_rate"], reverse=True)
    consistently_failing.sort(key=lambda x: x["fail_rate"], reverse=True)

    return {
        "total_scenarios":      total,
        "flaky_count":          len(flaky),
        "consistently_failing": len(consistently_failing),
        "stable_count":         len(stable),
        "flaky_rate":           round(flaky_rate, 4),
        "flaky_scenarios":      flaky[:50],
        "failing_scenarios":    consistently_failing[:20],
    }
