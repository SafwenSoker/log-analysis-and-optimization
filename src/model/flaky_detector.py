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
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from src.parser.log_parser import parse_log_file
from src.parser.models import BuildStatus

# Regex to extract failing Cucumber scenario names from logs
# Matches: [ERROR] FeatureName.ScenarioName  Time elapsed: X.XXX s  <<< FAILURE!
_FAIL_SCENARIO_RE = re.compile(
    r"\[ERROR\]\s+(\S+?\.\S+?)\s+Time elapsed:.+?<<< FAILURE!",
    re.I,
)

# Also catch scenario lines like:
# FiabilisationMontantNetSocial_FormationProfessionnelle.Fiabilisation montant net social
_FAIL_SCENARIO_RE2 = re.compile(
    r"^\s*\[ERROR\]\s+([\w.]+)\s+Time elapsed",
    re.M | re.I,
)

# Cucumber step-level failure line: "  Scenario: ..." followed by failure
_SCENARIO_NAME_RE = re.compile(
    r"Scenario(?:: | Outline: )(.+?)(?:\s*#|\s*$)",
    re.M,
)


@dataclass
class ScenarioHistory:
    name: str
    job_type: str
    runs: list[bool] = field(default_factory=list)      # True = passed, False = failed
    build_ids: list[int] = field(default_factory=list)  # corresponding build DB ids

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
        transitions = sum(
            1 for a, b in zip(self.runs, self.runs[1:]) if a != b
        )
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
    """Extract names of failing Cucumber scenarios from a log."""
    names = set()
    for pattern in (_FAIL_SCENARIO_RE, _FAIL_SCENARIO_RE2):
        for m in pattern.finditer(log_text):
            raw = m.group(1).strip()
            # Normalise: take the scenario part after the last dot if composite
            if "." in raw:
                scenario = raw.split(".", 1)[1].strip()
            else:
                scenario = raw
            if len(scenario) > 3:
                names.add(scenario[:200])
    return names


def _extract_all_scenarios(log_text: str) -> set[str]:
    """Extract all scenario names mentioned in the log (passed or failed)."""
    names = set()
    for m in _SCENARIO_NAME_RE.finditer(log_text):
        name = m.group(1).strip()
        if len(name) > 3:
            names.add(name[:200])
    return names


def analyse_flakiness(logs_dir: str | Path = "data/logs") -> dict[str, ScenarioHistory]:
    """
    Scan all log files, build per-scenario run histories,
    and return a dict of scenario_name → ScenarioHistory.
    """
    logs_dir = Path(logs_dir)
    log_files = sorted(logs_dir.glob("*.log.txt")) + sorted(logs_dir.glob("*.txt"))

    # Only Cucumber jobs produce scenario-level results
    histories: dict[str, ScenarioHistory] = {}

    for path in log_files:
        try:
            build = parse_log_file(path)
        except Exception:
            continue

        # Only process Selenium/Cucumber jobs
        from src.parser.models import JobType
        if build.job_type not in (
            JobType.FCTU_TRAIN1, JobType.FCTU_TRAIN2, JobType.PROD_ATIJ
        ):
            continue

        raw = build.raw_log
        failing = _extract_failing_scenarios(raw)
        all_scenarios = _extract_all_scenarios(raw)

        # If no scenarios detected at all, skip
        if not failing and not all_scenarios:
            continue

        # Scenarios that appear in log but not in failing set = passed
        passing = all_scenarios - failing

        job_type = build.job_type.value

        for name in failing:
            key = f"{job_type}::{name}"
            if key not in histories:
                histories[key] = ScenarioHistory(name=name, job_type=job_type)
            histories[key].runs.append(False)

        for name in passing:
            key = f"{job_type}::{name}"
            if key not in histories:
                histories[key] = ScenarioHistory(name=name, job_type=job_type)
            histories[key].runs.append(True)

    return histories


def get_flaky_summary(logs_dir: str | Path = "data/logs") -> dict:
    """
    Returns a summary dict with:
      - flaky       : list of flaky scenario dicts
      - consistently_failing : list
      - stable      : count
      - total       : total unique scenarios tracked
      - flaky_rate  : flaky / total
    """
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

    # Sort by alternation_rate desc
    flaky.sort(key=lambda x: x["alternation_rate"], reverse=True)
    consistently_failing.sort(key=lambda x: x["fail_rate"], reverse=True)

    return {
        "total_scenarios":       total,
        "flaky_count":           len(flaky),
        "consistently_failing":  len(consistently_failing),
        "stable_count":          len(stable),
        "flaky_rate":            round(flaky_rate, 4),
        "flaky_scenarios":       flaky[:50],       # top 50
        "failing_scenarios":     consistently_failing[:20],
    }
