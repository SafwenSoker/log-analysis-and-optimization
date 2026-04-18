from enum import Enum
from typing import Optional
from pydantic import BaseModel


class JobType(str, Enum):
    FCTU_TRAIN1 = "FCTU_Train1"
    FCTU_TRAIN2 = "FCTU_Train2"
    PROD_SERIALIZER = "PROD_Serializer"
    PROD_ATIJ = "PROD_ATIJ"
    UNKNOWN = "Unknown"


class BuildStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    UNSTABLE = "UNSTABLE"
    ABORTED = "ABORTED"
    UNKNOWN = "UNKNOWN"


class ErrorCategory(str, Enum):
    CONNECTION_REFUSED = "CONNECTION_REFUSED"
    NO_TESTS_EXECUTED = "NO_TESTS_EXECUTED"
    BUILD_ABORTED = "BUILD_ABORTED"
    CUCUMBER_TEST_FAILURE = "CUCUMBER_TEST_FAILURE"
    SERIALIZER_STEP_FAILURE = "SERIALIZER_STEP_FAILURE"
    SQL_ERROR = "SQL_ERROR"
    COMPILATION_ERROR = "COMPILATION_ERROR"
    GIT_ERROR = "GIT_ERROR"
    TIMEOUT = "TIMEOUT"
    UNKNOWN = "UNKNOWN"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class TestResults(BaseModel):
    tests_run: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    duration_seconds: Optional[float] = None


class ExtractedError(BaseModel):
    category: ErrorCategory
    message: str
    detail: Optional[str] = None
    line_number: Optional[int] = None


class ParsedBuild(BaseModel):
    filename: str
    job_type: JobType
    build_number: int
    status: BuildStatus
    triggered_by: Optional[str] = None
    upstream_job: Optional[str] = None
    git_commit: Optional[str] = None
    git_branch: Optional[str] = None
    git_commit_message: Optional[str] = None
    maven_command: Optional[str] = None
    cucumber_tags: Optional[str] = None
    test_results: TestResults = TestResults()
    errors: list[ExtractedError] = []
    duration_seconds: Optional[float] = None
    finished_at: Optional[str] = None
    raw_log: str = ""
    log_line_count: int = 0
