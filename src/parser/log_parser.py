import re
from pathlib import Path

from src.parser.models import (
    BuildStatus,
    ErrorCategory,
    ExtractedError,
    JobType,
    ParsedBuild,
    TestResults,
)

# --- Filename pattern matching ---
_FILENAME_PATTERNS = [
    (re.compile(r"FCTU_Train1build_(\d+)", re.I), JobType.FCTU_TRAIN1),
    (re.compile(r"FCTU_Train2build_(\d+)", re.I), JobType.FCTU_TRAIN2),
    (re.compile(r"PROD_Serializerbuild_(\d+)", re.I), JobType.PROD_SERIALIZER),
    (re.compile(r"^build_(\d+)", re.I), JobType.PROD_ATIJ),
]

_STATUS_RE = re.compile(r"^Finished:\s+(SUCCESS|FAILURE|UNSTABLE|ABORTED)", re.M)
_TRIGGERED_BY_RE = re.compile(r"Started by user (.+?) \((\w+)\)", re.I)
_UPSTREAM_RE = re.compile(r'Started by upstream project "(.+?)"', re.I)
_GIT_COMMIT_RE = re.compile(r"Checking out Revision ([a-f0-9]{40})")
_GIT_BRANCH_RE = re.compile(r"Checking out Revision [a-f0-9]+ \((.+?)\)")
_GIT_MSG_RE = re.compile(r'Commit message: "(.+?)"')
_MAVEN_CMD_RE = re.compile(r"Executing Maven:\s+(.+?)(?=\n|\[INFO\])", re.S)
_CUCUMBER_TAGS_RE = re.compile(r"-Dcucumber\.filter\.tags=(\S+)")
_TESTS_RUN_RE = re.compile(
    r"\[INFO\] Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)"
    r"(?:, Time elapsed: ([\d.]+) s)?"
)
_DURATION_RE = re.compile(r"Total time:\s+([\d.]+) s")
_FINISHED_AT_RE = re.compile(r"Finished at: (.+)")

# Error-specific patterns
_CONN_REFUSED_RE = re.compile(r"ERR_CONNECTION_REFUSED|est injoignable", re.I)
_NO_TESTS_RE = re.compile(r"No tests were executed|Tests run: 0", re.I)
_ABORTED_RE = re.compile(r"Build was aborted|Aborted by", re.I)
_TESTFAIL_RE = re.compile(r"<<< FAILURE!|There are test failures\.")
_SERIALIZER_FAIL_RE = re.compile(r"STEP .+? FAILED", re.I)
_SQL_ERR_RE = re.compile(r"SQLException|ORA-\d+|SQL.*error", re.I)
_COMPILE_ERR_RE = re.compile(r"COMPILATION ERROR|BUILD FAILURE.*compile", re.I | re.S)
_GIT_ERR_RE = re.compile(r"ERROR.*git|git.*ERROR|Repository .* not found", re.I)
_TIMEOUT_RE = re.compile(r"timed? ?out|timeout", re.I)

_FAILURE_SCENARIO_RE = re.compile(
    r"\[ERROR\] (.+?)\s+Time elapsed:.+?<<< FAILURE!", re.S
)


def _detect_job_type(filename: str) -> tuple[JobType, int]:
    stem = Path(filename).stem.split(".")[0]  # strip .log if double extension
    for pattern, job_type in _FILENAME_PATTERNS:
        m = pattern.search(stem)
        if m:
            return job_type, int(m.group(1))
    return JobType.UNKNOWN, 0


def _extract_test_results(text: str) -> TestResults:
    best = TestResults()
    for m in _TESTS_RUN_RE.finditer(text):
        candidate = TestResults(
            tests_run=int(m.group(1)),
            failures=int(m.group(2)),
            errors=int(m.group(3)),
            skipped=int(m.group(4)),
            duration_seconds=float(m.group(5)) if m.group(5) else None,
        )
        if candidate.tests_run >= best.tests_run:
            best = candidate
    return best


def _extract_errors(text: str, status: BuildStatus) -> list[ExtractedError]:
    errors: list[ExtractedError] = []

    if _ABORTED_RE.search(text):
        m = _ABORTED_RE.search(text)
        errors.append(ExtractedError(
            category=ErrorCategory.BUILD_ABORTED,
            message="Build was aborted",
            line_number=text[:m.start()].count("\n") + 1 if m else None,
        ))
        return errors  # aborted = no further analysis needed

    if _CONN_REFUSED_RE.search(text):
        m = _CONN_REFUSED_RE.search(text)
        # grab the URL from the assertion message
        url_m = re.search(r"injoignable : .+\n|ERR_CONNECTION_REFUSED", text)
        errors.append(ExtractedError(
            category=ErrorCategory.CONNECTION_REFUSED,
            message="Application server unreachable (ERR_CONNECTION_REFUSED)",
            detail=_first_line_around(text, m.start()),
            line_number=text[:m.start()].count("\n") + 1 if m else None,
        ))

    if _NO_TESTS_RE.search(text) and status == BuildStatus.FAILURE:
        m = _NO_TESTS_RE.search(text)
        errors.append(ExtractedError(
            category=ErrorCategory.NO_TESTS_EXECUTED,
            message="No tests were executed — check Cucumber tag filter or feature files",
            line_number=text[:m.start()].count("\n") + 1 if m else None,
        ))

    if _SERIALIZER_FAIL_RE.search(text):
        for m in _SERIALIZER_FAIL_RE.finditer(text):
            errors.append(ExtractedError(
                category=ErrorCategory.SERIALIZER_STEP_FAILURE,
                message=m.group(0),
                detail=_first_line_around(text, m.start()),
                line_number=text[:m.start()].count("\n") + 1,
            ))

    if _SQL_ERR_RE.search(text):
        m = _SQL_ERR_RE.search(text)
        errors.append(ExtractedError(
            category=ErrorCategory.SQL_ERROR,
            message="SQL error detected",
            detail=_first_line_around(text, m.start()),
            line_number=text[:m.start()].count("\n") + 1,
        ))

    if _COMPILE_ERR_RE.search(text):
        m = _COMPILE_ERR_RE.search(text)
        errors.append(ExtractedError(
            category=ErrorCategory.COMPILATION_ERROR,
            message="Maven compilation error",
            line_number=text[:m.start()].count("\n") + 1,
        ))

    if _GIT_ERR_RE.search(text):
        m = _GIT_ERR_RE.search(text)
        errors.append(ExtractedError(
            category=ErrorCategory.GIT_ERROR,
            message="Git operation failed",
            detail=_first_line_around(text, m.start()),
            line_number=text[:m.start()].count("\n") + 1,
        ))

    if _TIMEOUT_RE.search(text):
        m = _TIMEOUT_RE.search(text)
        errors.append(ExtractedError(
            category=ErrorCategory.TIMEOUT,
            message="Timeout detected",
            detail=_first_line_around(text, m.start()),
            line_number=text[:m.start()].count("\n") + 1,
        ))

    if _TESTFAIL_RE.search(text) and not errors:
        for m in _FAILURE_SCENARIO_RE.finditer(text):
            scenario = m.group(1).strip()
            errors.append(ExtractedError(
                category=ErrorCategory.CUCUMBER_TEST_FAILURE,
                message=f"Cucumber scenario failed: {scenario[:120]}",
                line_number=text[:m.start()].count("\n") + 1,
            ))
            if len(errors) >= 5:
                break

    if not errors and status in (BuildStatus.FAILURE, BuildStatus.UNSTABLE):
        errors.append(ExtractedError(
            category=ErrorCategory.UNKNOWN,
            message="Build failed — no specific error pattern matched",
        ))

    return errors


def _first_line_around(text: str, pos: int, context: int = 200) -> str:
    start = max(0, pos - 50)
    end = min(len(text), pos + context)
    snippet = text[start:end]
    return snippet.split("\n")[0].strip()[:250]


def parse_log_file(filepath: str | Path) -> ParsedBuild:
    path = Path(filepath)
    raw = path.read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()

    job_type, build_number = _detect_job_type(path.name)

    # Status
    status_m = _STATUS_RE.search(raw)
    status = BuildStatus(status_m.group(1)) if status_m else BuildStatus.UNKNOWN

    # Triggered by
    triggered_by = None
    tb_m = _TRIGGERED_BY_RE.search(raw)
    if tb_m:
        triggered_by = f"{tb_m.group(1)} ({tb_m.group(2)})"

    upstream = None
    up_m = _UPSTREAM_RE.search(raw)
    if up_m:
        upstream = up_m.group(1)

    # Git metadata
    git_commit = None
    gc_m = _GIT_COMMIT_RE.search(raw)
    if gc_m:
        git_commit = gc_m.group(1)

    git_branch = None
    gb_m = _GIT_BRANCH_RE.search(raw)
    if gb_m:
        git_branch = gb_m.group(1)

    git_msg = None
    gm_m = _GIT_MSG_RE.search(raw)
    if gm_m:
        git_msg = gm_m.group(1)

    # Maven / Cucumber
    maven_cmd = None
    mc_m = _MAVEN_CMD_RE.search(raw)
    if mc_m:
        maven_cmd = mc_m.group(1).strip()[:500]

    cucumber_tags = None
    ct_m = _CUCUMBER_TAGS_RE.search(raw)
    if ct_m:
        cucumber_tags = ct_m.group(1)

    # Test results
    test_results = _extract_test_results(raw)

    # Duration
    duration = None
    dur_m = _DURATION_RE.search(raw)
    if dur_m:
        duration = float(dur_m.group(1))

    finished_at = None
    fa_m = _FINISHED_AT_RE.search(raw)
    if fa_m:
        finished_at = fa_m.group(1).strip()

    errors = _extract_errors(raw, status)

    return ParsedBuild(
        filename=path.name,
        job_type=job_type,
        build_number=build_number,
        status=status,
        triggered_by=triggered_by,
        upstream_job=upstream,
        git_commit=git_commit,
        git_branch=git_branch,
        git_commit_message=git_msg,
        maven_command=maven_cmd,
        cucumber_tags=cucumber_tags,
        test_results=test_results,
        errors=errors,
        duration_seconds=duration,
        finished_at=finished_at,
        raw_log=raw,
        log_line_count=len(lines),
    )


def parse_log_text(content: str, filename: str = "uploaded.log.txt") -> ParsedBuild:
    import tempfile, os
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix=filename.rstrip(".txt"),
        delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        tmp_path = f.name
    try:
        return parse_log_file(tmp_path)
    finally:
        os.unlink(tmp_path)
