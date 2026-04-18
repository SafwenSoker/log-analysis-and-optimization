from src.parser.models import (
    BuildStatus,
    ErrorCategory,
    ParsedBuild,
    Severity,
)

# Severity mapping per error category
_SEVERITY_MAP: dict[ErrorCategory, Severity] = {
    ErrorCategory.CONNECTION_REFUSED: Severity.CRITICAL,
    ErrorCategory.COMPILATION_ERROR: Severity.CRITICAL,
    ErrorCategory.GIT_ERROR: Severity.CRITICAL,
    ErrorCategory.NO_TESTS_EXECUTED: Severity.HIGH,
    ErrorCategory.SERIALIZER_STEP_FAILURE: Severity.HIGH,
    ErrorCategory.SQL_ERROR: Severity.HIGH,
    ErrorCategory.CUCUMBER_TEST_FAILURE: Severity.MEDIUM,
    ErrorCategory.TIMEOUT: Severity.MEDIUM,
    ErrorCategory.BUILD_ABORTED: Severity.LOW,
    ErrorCategory.UNKNOWN: Severity.MEDIUM,
}

# Human-readable labels
_CATEGORY_LABELS: dict[ErrorCategory, str] = {
    ErrorCategory.CONNECTION_REFUSED: "Application server unreachable",
    ErrorCategory.NO_TESTS_EXECUTED: "No matching test scenarios",
    ErrorCategory.BUILD_ABORTED: "Build manually aborted",
    ErrorCategory.CUCUMBER_TEST_FAILURE: "Cucumber scenario failure",
    ErrorCategory.SERIALIZER_STEP_FAILURE: "Test data serialization step failed",
    ErrorCategory.SQL_ERROR: "Database / SQL error",
    ErrorCategory.COMPILATION_ERROR: "Maven compilation error",
    ErrorCategory.GIT_ERROR: "Git checkout / fetch error",
    ErrorCategory.TIMEOUT: "Step timed out",
    ErrorCategory.UNKNOWN: "Unclassified failure",
}

# Debugging recommendations per category
_RECOMMENDATIONS: dict[ErrorCategory, list[str]] = {
    ErrorCategory.CONNECTION_REFUSED: [
        "Verify the HRA application server is running at the target URL.",
        "Check network connectivity between the Jenkins agent and the app server.",
        "Confirm the correct environment URL is passed in the `-Durl` Maven parameter.",
        "Check if a recent deployment or restart caused temporary downtime.",
    ],
    ErrorCategory.NO_TESTS_EXECUTED: [
        "Verify the Cucumber tag filter (`-Dcucumber.filter.tags`) matches tags defined in the .feature files.",
        "Check that feature files exist in `src/test/resources/features/`.",
        "Ensure the `develop` branch contains the expected scenarios.",
        "Review recent commits — a tag rename or feature file deletion could cause this.",
    ],
    ErrorCategory.BUILD_ABORTED: [
        "Build was cancelled — check upstream pipeline for a timeout or manual cancellation.",
        "Review the upstream `DEV_TNR_PARALLEL` or `PROD_TNR_PARALLEL` job for cancellation reason.",
        "No corrective action needed unless this abort was unexpected.",
    ],
    ErrorCategory.CUCUMBER_TEST_FAILURE: [
        "Review the failed scenario in the Cucumber HTML report for the exact failing step.",
        "Check whether the UI element the step interacts with has changed (locator drift).",
        "Verify test data — the scenario may depend on a pre-condition that was not met.",
        "Run the scenario in isolation to confirm reproducibility.",
    ],
    ErrorCategory.SERIALIZER_STEP_FAILURE: [
        "Review the WonderTesting / Testbook step output for the specific failure message.",
        "Verify the target environment (`qa03`/`qa54`/`qa55`) is accessible from SDLC15.",
        "Check that the test data tables (`zy00`, `AB10`, `ZX00`, `ZZ00`) are reachable.",
        "Confirm the test case ID is valid and configured in the serializer scripts.",
    ],
    ErrorCategory.SQL_ERROR: [
        "Check database connectivity to the SDLC15 remote server.",
        "Verify the SQL credentials and permissions for the delete operations.",
        "Look for table locks — a previous run may not have completed its cleanup.",
    ],
    ErrorCategory.COMPILATION_ERROR: [
        "Run `mvn clean compile` locally to reproduce the error.",
        "Check for incompatible dependency versions introduced in a recent commit.",
        "Review the Nexus repository for missing artifacts.",
    ],
    ErrorCategory.GIT_ERROR: [
        "Verify the Bitbucket server (`hra-bitbucket.ptx.fr.sopra`) is reachable.",
        "Check the Jenkins credential (`cc3ffaa8-...`) has not expired.",
        "Confirm the branch (`develop` or `master`) still exists in the remote repository.",
    ],
    ErrorCategory.TIMEOUT: [
        "Identify which step timed out — check the step duration in the log.",
        "Increase the timeout if the step consistently takes longer than expected.",
        "Check for infrastructure slowness (network, database, app server) at the time of failure.",
    ],
    ErrorCategory.UNKNOWN: [
        "Review the full build log for ERROR or FAILURE keywords near the end.",
        "Compare with a recent successful build of the same job to identify what changed.",
        "Check the Jenkins agent's disk space, memory, and process limits.",
    ],
}


class ClassificationResult:
    __slots__ = ("primary_category", "all_categories", "severity", "label", "recommendations")

    def __init__(
        self,
        primary_category: ErrorCategory,
        all_categories: list[ErrorCategory],
        severity: Severity,
        label: str,
        recommendations: list[str],
    ):
        self.primary_category = primary_category
        self.all_categories = all_categories
        self.severity = severity
        self.label = label
        self.recommendations = recommendations

    def to_dict(self) -> dict:
        return {
            "primary_category": self.primary_category.value,
            "all_categories": [c.value for c in self.all_categories],
            "severity": self.severity.value,
            "label": self.label,
            "recommendations": self.recommendations,
        }


def classify(build: ParsedBuild) -> ClassificationResult:
    if build.status == BuildStatus.SUCCESS:
        return ClassificationResult(
            primary_category=ErrorCategory.UNKNOWN,
            all_categories=[],
            severity=Severity.INFO,
            label="Build succeeded",
            recommendations=[],
        )

    if not build.errors:
        primary = ErrorCategory.UNKNOWN
    else:
        # Pick the highest-severity error as primary
        primary = max(
            (e.category for e in build.errors),
            key=lambda c: list(Severity).index(_SEVERITY_MAP.get(c, Severity.MEDIUM)),
        )

    all_cats = list(dict.fromkeys(e.category for e in build.errors))
    severity = _SEVERITY_MAP.get(primary, Severity.MEDIUM)
    label = _CATEGORY_LABELS.get(primary, "Unknown error")
    recommendations = _RECOMMENDATIONS.get(primary, _RECOMMENDATIONS[ErrorCategory.UNKNOWN])

    return ClassificationResult(
        primary_category=primary,
        all_categories=all_cats,
        severity=severity,
        label=label,
        recommendations=recommendations,
    )
