# CLAUDE.md — Jenkins Log Analysis & Optimization Platform

## Project Overview

A FastAPI web platform that automatically analyses Jenkins CI/CD build logs.
It parses raw log files, classifies failures by root cause using a rule-based
classifier and a trained ML model, and surfaces actionable recommendations via
a web dashboard.

Target Jenkins pipelines: FCTU_Train1, FCTU_Train2, PROD_Serializer, PROD_ATIJ.

---

## Architecture

```
src/
├── api/
│   ├── main.py          — FastAPI app, router registration, auth dependency
│   ├── auth.py          — API key middleware (X-API-Key header)
│   ├── routes/
│   │   ├── builds.py    — build list & detail endpoints
│   │   ├── analysis.py  — analysis trigger & results
│   │   ├── jenkins.py   — webhook + bulk ingest + live fetch from Jenkins API
│   │   ├── upload.py    — manual log file upload
│   │   └── model.py     — model training trigger & metrics
│   └── templates/       — Jinja2 HTML (dashboard, build_detail, flaky)
├── parser/
│   ├── log_parser.py    — regex-based extraction of status, errors, test results
│   └── models.py        — Pydantic models: ParsedBuild, ErrorCategory, JobType…
├── classifier/
│   └── error_classifier.py  — rule-based classifier: category → severity + recommendations
├── model/
│   ├── features.py      — structured features + TF-IDF text extraction + noise cleaning
│   ├── trainer.py       — full ML training pipeline (4 models, CV, 300/25 split)
│   ├── predictor.py     — inference: ML model with rule-based fallback
│   └── flaky_detector.py — Cucumber scenario flakiness detection across builds
└── storage/
    └── database.py      — SQLite via SQLAlchemy Core (builds, analyses, flaky_tests)

data/
├── logs/        — raw Jenkins log files (*.log.txt)
├── labels.csv   — manual annotations: filename, label, status (ground truth for ML)
├── model.joblib — trained pipeline (pipeline + LabelEncoder)
└── model_metrics.json — last training results
```

---

## Environment Setup

```bash
bash setup.sh          # create .venv and install dependencies (run once)
```

Create a `.env` file at the project root:

```env
JENKINS_URL=http://your-jenkins-server
JENKINS_USER=admin
JENKINS_TOKEN=your-api-token
API_KEY=your-secret-key        # leave empty to disable auth in dev
LOG_DIR=data/logs
DB_PATH=data/analysis.db
```

---

## Running the Project

```bash
bash run.sh            # start API server on port 8000
bash ingest.sh         # bulk-ingest all logs from data/logs/ (run after server is up)
python train.py        # retrain the ML model
```

Dev server (with auto-reload):
```bash
source .venv/Scripts/activate
python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
```

Production (Docker):
```bash
docker-compose up --build
```

---

## Running Tests

```bash
source .venv/Scripts/activate
python -m pytest tests/ -v
```

40 tests covering parser, classifier, and feature extraction.
Tests use synthetic mini-logs as fixtures — no real log files needed.

---

## ML Pipeline

### Error categories (8 active classes)
| Category | Description |
|---|---|
| `SELENIUM_UI_FAILURE` | WebElement not found via XPath |
| `SELENIUM_DRIVER_ERROR` | ChromeDriver absent or crashed |
| `NO_TESTS_EXECUTED` | Maven ran but zero tests matched |
| `BUILD_ABORTED` | Manually cancelled |
| `SERIALIZER_STEP_FAILURE` | PROD_Serializer batch step failed |
| `COMPILATION_ERROR` | Maven compilation error |
| `CONNECTION_REFUSED` | App server unreachable |
| `SUCCESS` | Build passed |

Classes with fewer than 5 samples (`MAVEN_DEPENDENCY_ERROR`, `JVM_ERROR`, `UNKNOWN`)
are automatically excluded from training.

### Training split strategy
- **25 logs** → validation set, held out entirely before training
- **294 logs** → train + test pool (80/20 internal split for model selection)
- **5-fold stratified CV** on the train set to compare 4 candidate models
- Best model selected by weighted F1, then fit on all 294 logs
- Final evaluation reported on the 25 validation logs

### Labels
`data/labels.csv` is the ground truth. It was built by reading each log and
assigning a category based on the actual error content — independently from the
rule-based classifier. Do not regenerate it automatically; update it manually
when new log types appear.

To retrain after adding new logs to `data/logs/`:
1. Add the new filenames + labels to `data/labels.csv`
2. Run `python train.py`

---

## API Authentication

Set `API_KEY=your-secret` in `.env`. All API routes then require:

```
X-API-Key: your-secret
```

HTML pages (`/`, `/builds/{id}`, `/flaky`) are always public.
If `API_KEY` is empty, auth is disabled (dev mode).

---

## Key Design Decisions

- **Rule-based classifier is the fallback**: if `data/model.joblib` does not exist,
  `predictor.predict()` falls back to the rule-based classifier automatically.
- **No double-counting**: glob patterns `*.log`, `*.log.txt`, `*.txt` are deduplicated
  by resolved path before ingestion and training.
- **TIMEOUT false positive**: the Jenkins Git plugin uses `# timeout=10` in every
  git command. The TIMEOUT regex only matches real timeout messages
  (`Timeout waiting`, `process timed out`, etc.).
- **Text cleaning before TF-IDF**: `_clean_log_text()` removes timestamps, URLs,
  file paths, Git hashes, and version numbers to reduce noise.

---

## Jenkins Webhook Integration

Configure in Jenkins → Post-build Actions → HTTP Request:
```
URL: http://<host>:8000/jenkins/webhook
Content-Type: application/json
Body: {"job_name":"$JOB_NAME","build_number":$BUILD_NUMBER,"status":"$BUILD_STATUS","log_url":"$BUILD_URL/consoleText"}
```

The platform and Jenkins communicate over VPN — ensure the host running this
server is reachable from the Jenkins agent network.
