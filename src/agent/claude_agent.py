"""
Claude-powered root cause analysis agent.

Uses prompt caching on the system prompt + few-shot examples to keep costs low
across repeated per-build analysis calls.
"""

import json
import re

import anthropic

from src.classifier.error_classifier import ClassificationResult
from src.parser.models import BuildStatus, ParsedBuild

_client: anthropic.Anthropic | None = None

SYSTEM_PROMPT = """\
You are an expert CI/CD and test automation engineer specialising in Jenkins pipelines \
for Sopra HR Software (HRA — HR Access), a French HR and payroll application.

## Pipeline context
The Jenkins environment runs three types of jobs:

1. **FCTU_Train1 / FCTU_Train2** (`DEV_TNR_Train1_Launcher` / `DEV_TNR_Train2_Launcher`)
   - Triggered by upstream job `DEV_TNR_PARALLEL` (both trains run in parallel).
   - Maven + Selenium + Cucumber BDD tests against a web portal (HRA-space).
   - Tests HR features: payroll (paie), DSN (Déclaration Sociale Nominative), employee mutations.
   - Browser: Chrome headless via ChromeDriver on Windows Server 2016.
   - Git repo: `com.soprahr.tnra.rmit.rd.edsn.init.hra`, branch `develop`.

2. **PROD_Serializer** (`PROD_Serializer`)
   - Triggered by `PROD_Pipeline_TestBook` → `PROD_INITIALISATION_TNR`.
   - Prepares test data: SQL cleanup on tables (zy00, AB10, ZX00, ZZ00) on SDLC15 server,
     then injects data via WonderTesting scripts (`.bat` / `.js`).
   - Uses environments: qa03, qa54, qa55.

3. **PROD_ATIJ** (`PROD_HRA_ATIJ_TEST_SELENIUM`)
   - Same Selenium/Cucumber stack as FCTU trains but targets the PROD/ATIJ environment.
   - Cucumber tag: `@ALL` or specific feature folder filters.

## Common failure causes
- `ERR_CONNECTION_REFUSED` → HRA application server is down or unreachable.
- `No tests were executed` → Cucumber tag filter doesn't match any feature file tags.
- `Build was aborted` → Manual cancellation or upstream pipeline timeout.
- `STEP X FAILED` → WonderTesting / Testbook step failure in PROD_Serializer.
- Compilation errors → Dependency issue or broken commit in `develop`.
- Git errors → Bitbucket server unreachable or credentials expired.

## Your task
When given a structured build report, perform a thorough root cause analysis. \
Be concise, specific, and actionable. Always reference exact log evidence. \
Respond strictly in JSON as specified.
"""

_ANALYSIS_SCHEMA = {
    "root_cause": "string — one sentence, the most likely technical root cause",
    "explanation": "string — 2-4 sentences explaining what happened and why",
    "confidence": "string — HIGH | MEDIUM | LOW",
    "evidence": ["list of direct log excerpts or facts that support the diagnosis"],
    "recommendations": ["list of 2-5 concrete, actionable steps to fix or prevent recurrence"],
    "recurring_risk": "string — YES | NO | UNKNOWN — whether this is likely to recur without action",
}


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _build_log_excerpt(build: ParsedBuild, max_chars: int = 8000) -> str:
    """Return the most diagnostic portion of the raw log."""
    raw = build.raw_log
    if len(raw) <= max_chars:
        return raw

    # Always include tail (where final status, errors, and stack traces appear)
    tail_size = max_chars // 2
    head_size = max_chars - tail_size
    return raw[:head_size] + "\n\n[... middle truncated ...]\n\n" + raw[-tail_size:]


def _build_user_message(build: ParsedBuild, classification: ClassificationResult) -> str:
    errors_json = [
        {
            "category": e.category.value,
            "message": e.message,
            "detail": e.detail,
            "line": e.line_number,
        }
        for e in build.errors
    ]

    summary = {
        "filename": build.filename,
        "job_type": build.job_type.value,
        "build_number": build.build_number,
        "status": build.status.value,
        "triggered_by": build.triggered_by,
        "upstream_job": build.upstream_job,
        "git_branch": build.git_branch,
        "git_commit_message": build.git_commit_message,
        "cucumber_tags": build.cucumber_tags,
        "test_results": {
            "run": build.test_results.tests_run,
            "failures": build.test_results.failures,
            "errors": build.test_results.errors,
            "skipped": build.test_results.skipped,
        },
        "duration_seconds": build.duration_seconds,
        "finished_at": build.finished_at,
        "rule_based_classification": classification.to_dict(),
        "extracted_errors": errors_json,
    }

    log_excerpt = _build_log_excerpt(build)

    return f"""## Build summary (structured)
```json
{json.dumps(summary, indent=2, ensure_ascii=False)}
```

## Raw log excerpt
```
{log_excerpt}
```

## Instructions
Analyse this build and respond with a JSON object matching this schema:
```json
{json.dumps(_ANALYSIS_SCHEMA, indent=2)}
```
Return only the JSON object — no markdown fences, no extra text."""


def analyse_build(build: ParsedBuild, classification: ClassificationResult) -> dict:
    """
    Call the Claude API to produce a root cause analysis for the given build.
    Returns a dict matching _ANALYSIS_SCHEMA.
    Falls back to a rule-based response if the API call fails.
    """
    if build.status == BuildStatus.SUCCESS:
        return {
            "root_cause": "No failure — build succeeded.",
            "explanation": "All tests passed and the build completed without errors.",
            "confidence": "HIGH",
            "evidence": [f"Finished: SUCCESS"],
            "recommendations": [],
            "recurring_risk": "NO",
        }

    client = _get_client()
    user_message = _build_user_message(build, classification)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},  # prompt caching
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )

        raw_text = response.content[0].text.strip()
        # Strip markdown fences if the model added them despite instructions
        raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

        result = json.loads(raw_text)
        return result

    except json.JSONDecodeError:
        return _fallback_analysis(classification)
    except anthropic.APIError as e:
        return _fallback_analysis(classification, error=str(e))


def _fallback_analysis(
    classification: ClassificationResult, error: str | None = None
) -> dict:
    note = f" (Claude API unavailable: {error})" if error else " (Claude API unavailable)"
    return {
        "root_cause": f"{classification.label}{note}",
        "explanation": "Rule-based classification was used as fallback.",
        "confidence": "LOW",
        "evidence": [],
        "recommendations": classification.recommendations,
        "recurring_risk": "UNKNOWN",
    }
