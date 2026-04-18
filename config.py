import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
JENKINS_URL: str       = os.getenv("JENKINS_URL", "")
JENKINS_USER: str      = os.getenv("JENKINS_USER", "admin")
JENKINS_TOKEN: str     = os.getenv("JENKINS_TOKEN", "")

LOG_DIR: Path  = Path(os.getenv("LOG_DIR", "data/logs"))
DB_PATH: str   = os.getenv("DB_PATH", "data/analysis.db")
