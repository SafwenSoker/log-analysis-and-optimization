"""Tests for the log parser."""
import pytest
from src.parser.log_parser import parse_log_text
from src.parser.models import BuildStatus, ErrorCategory, JobType


def _make_log(body: str, status: str = "FAILURE") -> str:
    return (
        "Started by user Test User (tuser)\n"
        "Checking out Revision abc123def456abc123def456abc123def456abc1 (refs/heads/develop)\n"
        "Commit message: \"fix: update test\"\n"
        f"{body}\n"
        f"Finished: {status}\n"
    )


class TestBuildStatus:
    def test_success(self):
        build = parse_log_text(_make_log("BUILD SUCCESS", "SUCCESS"), "build_1.log.txt")
        assert build.status == BuildStatus.SUCCESS

    def test_failure(self):
        build = parse_log_text(_make_log("BUILD FAILURE", "FAILURE"), "build_1.log.txt")
        assert build.status == BuildStatus.FAILURE

    def test_unstable(self):
        build = parse_log_text(_make_log("some output", "UNSTABLE"), "build_1.log.txt")
        assert build.status == BuildStatus.UNSTABLE

    def test_aborted(self):
        build = parse_log_text(_make_log("Build was aborted", "ABORTED"), "build_1.log.txt")
        assert build.status == BuildStatus.ABORTED


class TestJobTypeDetection:
    def test_fctu_train1(self):
        build = parse_log_text(_make_log(""), "FCTU_Train1build_42.log.txt")
        assert build.job_type == JobType.FCTU_TRAIN1
        assert build.build_number == 42

    def test_prod_serializer(self):
        build = parse_log_text(_make_log(""), "PROD_Serializerbuild_1291.log.txt")
        assert build.job_type == JobType.PROD_SERIALIZER
        assert build.build_number == 1291

    def test_prod_atij(self):
        build = parse_log_text(_make_log(""), "build_7.log.txt")
        assert build.job_type == JobType.PROD_ATIJ
        assert build.build_number == 7


class TestErrorExtraction:
    def test_selenium_ui_failure(self):
        log = _make_log("ERROR WEGet : WebElement NULL via XPATH=//div[@id='main']", "UNSTABLE")
        build = parse_log_text(log, "build_1.log.txt")
        categories = [e.category for e in build.errors]
        assert ErrorCategory.SELENIUM_UI_FAILURE in categories

    def test_selenium_driver_error(self):
        log = _make_log("INFO >ERROR: The process \"chromedriver.exe\" not found.", "UNSTABLE")
        build = parse_log_text(log, "build_1.log.txt")
        categories = [e.category for e in build.errors]
        assert ErrorCategory.SELENIUM_DRIVER_ERROR in categories

    def test_build_aborted(self):
        log = _make_log("Build was aborted\nAborted by admin", "ABORTED")
        build = parse_log_text(log, "build_1.log.txt")
        assert any(e.category == ErrorCategory.BUILD_ABORTED for e in build.errors)

    def test_serializer_step_failure(self):
        log = _make_log("STEP Start_08_DSNTB_HireEmployee.bat FAILED: .1 .", "FAILURE")
        build = parse_log_text(log, "PROD_Serializerbuild_1.log.txt")
        categories = [e.category for e in build.errors]
        assert ErrorCategory.SERIALIZER_STEP_FAILURE in categories

    def test_maven_dependency_error(self):
        log = _make_log(
            "ERROR: Failed to parse POMs\n"
            "org.apache.maven.project.ProjectBuildingException: Some problems",
            "FAILURE",
        )
        build = parse_log_text(log, "build_1.log.txt")
        categories = [e.category for e in build.errors]
        assert ErrorCategory.MAVEN_DEPENDENCY_ERROR in categories

    def test_jvm_error(self):
        log = _make_log(
            "Error: Could not create the Java Virtual Machine.\n"
            "Error: A fatal exception has occurred. Program will exit.\n"
            "ERROR: Failed to launch Maven. Exit code = 1",
            "FAILURE",
        )
        build = parse_log_text(log, "build_1.log.txt")
        categories = [e.category for e in build.errors]
        assert ErrorCategory.JVM_ERROR in categories

    def test_no_error_on_success(self):
        log = _make_log("BUILD SUCCESS", "SUCCESS")
        build = parse_log_text(log, "build_1.log.txt")
        assert build.errors == []

    def test_timeout_false_positive_git_param(self):
        """git # timeout=10 must NOT trigger TIMEOUT category."""
        log = _make_log(
            "> git.exe fetch --tags --force -- http://bitbucket/repo.git # timeout=10",
            "UNSTABLE",
        )
        build = parse_log_text(log, "build_1.log.txt")
        categories = [e.category for e in build.errors]
        assert ErrorCategory.TIMEOUT not in categories


class TestTestResultExtraction:
    def test_extracts_test_counts(self):
        log = _make_log(
            "[INFO] Tests run: 42, Failures: 3, Errors: 1, Skipped: 2, Time elapsed: 120.5 s",
            "UNSTABLE",
        )
        build = parse_log_text(log, "build_1.log.txt")
        assert build.test_results.tests_run == 42
        assert build.test_results.failures == 3
        assert build.test_results.errors == 1
        assert build.test_results.skipped == 2

    def test_picks_largest_run(self):
        """Parser should pick the summary with the most tests_run."""
        log = _make_log(
            "[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0\n"
            "[INFO] Tests run: 100, Failures: 2, Errors: 0, Skipped: 1",
            "UNSTABLE",
        )
        build = parse_log_text(log, "build_1.log.txt")
        assert build.test_results.tests_run == 100
