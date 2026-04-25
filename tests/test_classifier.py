"""Tests for the rule-based error classifier."""
import pytest
from src.parser.log_parser import parse_log_text
from src.classifier.error_classifier import classify
from src.parser.models import BuildStatus, ErrorCategory, Severity


def _classify_log(body: str, status: str = "FAILURE", filename: str = "build_1.log.txt"):
    log = f"Started by user Test (t)\n{body}\nFinished: {status}\n"
    build = parse_log_text(log, filename)
    return classify(build)


class TestSuccessClassification:
    def test_success_has_info_severity(self):
        result = _classify_log("BUILD SUCCESS", "SUCCESS")
        assert result.severity == Severity.INFO

    def test_success_has_no_recommendations(self):
        result = _classify_log("BUILD SUCCESS", "SUCCESS")
        assert result.recommendations == []


class TestSeverityMapping:
    def test_selenium_ui_is_medium(self):
        result = _classify_log(
            "ERROR WEGet : WebElement NULL via XPATH=//div", "UNSTABLE"
        )
        assert result.severity == Severity.MEDIUM

    def test_selenium_driver_is_high(self):
        result = _classify_log(
            'INFO >ERROR: The process "chromedriver.exe" not found.', "UNSTABLE"
        )
        assert result.severity == Severity.HIGH

    def test_jvm_is_critical(self):
        result = _classify_log(
            "Error: Could not create the Java Virtual Machine.\n"
            "ERROR: Failed to launch Maven. Exit code = 1",
            "FAILURE",
        )
        assert result.severity == Severity.CRITICAL

    def test_aborted_is_low(self):
        result = _classify_log("Build was aborted", "ABORTED")
        assert result.severity == Severity.LOW

    def test_maven_dep_is_high(self):
        result = _classify_log(
            "ERROR: Failed to parse POMs\n"
            "org.apache.maven.project.ProjectBuildingException",
            "FAILURE",
        )
        assert result.severity == Severity.HIGH


class TestRecommendations:
    def test_all_failure_categories_have_recommendations(self):
        cases = [
            ("ERROR WEGet : WebElement NULL via XPATH=//div", "UNSTABLE"),
            ('INFO >ERROR: The process "chromedriver.exe" not found.', "UNSTABLE"),
            ("Build was aborted", "ABORTED"),
            ("STEP Start_08.bat FAILED: .1 .", "FAILURE"),
            ("Error: Could not create the Java Virtual Machine.\nERROR: Failed to launch Maven. Exit code = 1", "FAILURE"),
            ("ERROR: Failed to parse POMs", "FAILURE"),
        ]
        for body, status in cases:
            result = _classify_log(body, status)
            assert len(result.recommendations) > 0, (
                f"No recommendations for body={body!r}"
            )

    def test_aborted_has_no_action_needed(self):
        result = _classify_log("Build was aborted", "ABORTED")
        text = " ".join(result.recommendations).lower()
        assert "cancel" in text or "no corrective" in text or "check" in text


class TestPrimaryCategory:
    def test_driver_takes_priority_over_ui(self):
        """When both driver error and UI failure are present, driver should be primary."""
        result = _classify_log(
            'INFO >ERROR: The process "chromedriver.exe" not found.\n'
            "ERROR WEGet : WebElement NULL via XPATH=//div",
            "UNSTABLE",
        )
        assert result.primary_category == ErrorCategory.SELENIUM_DRIVER_ERROR
