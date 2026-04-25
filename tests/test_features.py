"""Tests for feature extraction and text cleaning."""
import numpy as np
import pytest
from src.parser.log_parser import parse_log_text
from src.model.features import extract_structured, extract_text_section, _clean_log_text, N_STRUCTURED


def _build(body: str, status: str = "FAILURE", filename: str = "build_1.log.txt"):
    log = f"Started by user Test (t)\n{body}\nFinished: {status}\n"
    return parse_log_text(log, filename)


class TestCleanLogText:
    def test_removes_timestamps(self):
        cleaned = _clean_log_text("2024-01-15 14:23:01 ERROR something failed")
        assert "2024-01-15" not in cleaned
        assert "TIMESTAMP" in cleaned

    def test_removes_urls(self):
        cleaned = _clean_log_text("Failed to connect https://hra-bitbucket.ptx.fr.sopra/repo")
        assert "https://" not in cleaned
        assert "URL" in cleaned

    def test_removes_paths(self):
        cleaned = _clean_log_text("File not found: /var/jenkins/workspace/build/target")
        assert "/var/jenkins" not in cleaned
        assert "PATH" in cleaned

    def test_removes_git_hashes(self):
        cleaned = _clean_log_text("Checking out abc123def456abc123def456abc123def456abc1")
        assert "abc123def456" not in cleaned
        assert "GIT_HASH" in cleaned

    def test_filters_noisy_info_lines(self):
        cleaned = _clean_log_text(
            "[INFO] Downloading from nexus: artifact.jar\n"
            "[ERROR] Build failed"
        )
        assert "Downloading" not in cleaned
        assert "Build failed" in cleaned

    def test_preserves_error_content(self):
        cleaned = _clean_log_text("WebElement NULL via XPATH=//div[@id='main']")
        assert "WebElement" in cleaned

    def test_git_timeout_param_not_treated_as_hash(self):
        """# timeout=10 in git commands should survive cleaning (not be a GIT_HASH)."""
        cleaned = _clean_log_text("> git.exe fetch --tags -- http://repo.git # timeout=10")
        assert "timeout" in cleaned.lower()


class TestExtractStructured:
    def test_output_shape(self):
        build = _build("some log", "SUCCESS")
        vec = extract_structured(build)
        assert vec.shape == (N_STRUCTURED,)
        assert vec.dtype == np.float32

    def test_keyword_flag_selenium_ui(self):
        build = _build("WebElement NULL via XPATH=//div", "UNSTABLE")
        vec = extract_structured(build)
        assert vec.sum() > 0

    def test_success_build_has_no_failure_rate(self):
        build = _build("BUILD SUCCESS", "SUCCESS")
        vec = extract_structured(build)
        # failure_rate and error_rate should be 0 for success with no test results
        from src.model.features import N_JOB_TYPES, N_KEYWORDS
        failure_rate = vec[N_JOB_TYPES + N_KEYWORDS + 1]
        assert failure_rate == 0.0


class TestExtractTextSection:
    def test_returns_string(self):
        build = _build("ERROR something happened", "FAILURE")
        text = extract_text_section(build)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_includes_error_lines(self):
        build = _build("[ERROR] Something went wrong here", "FAILURE")
        text = extract_text_section(build)
        assert "Something went wrong" in text

    def test_no_raw_timestamps_in_output(self):
        build = _build("2024-01-15 14:23:01 [ERROR] failed", "FAILURE")
        text = extract_text_section(build)
        assert "2024-01-15" not in text
