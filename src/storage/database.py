"""
SQLite storage layer using SQLAlchemy Core.
Tables: builds, analyses, flaky_tests
"""

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer,
    MetaData, String, Table, Text, create_engine, select, update,
)
from sqlalchemy.engine import Engine

_engine: Engine | None = None
metadata = MetaData()

builds_table = Table(
    "builds", metadata,
    Column("id",                Integer, primary_key=True, autoincrement=True),
    Column("filename",          String(255), unique=True, nullable=False),
    Column("job_type",          String(50)),
    Column("build_number",      Integer),
    Column("status",            String(20)),
    Column("triggered_by",      String(255)),
    Column("upstream_job",      String(255)),
    Column("git_commit",        String(40)),
    Column("git_branch",        String(255)),
    Column("git_commit_message",Text),
    Column("cucumber_tags",     String(255)),
    Column("tests_run",         Integer, default=0),
    Column("test_failures",     Integer, default=0),
    Column("test_errors",       Integer, default=0),
    Column("test_skipped",      Integer, default=0),
    Column("duration_seconds",  Float),
    Column("finished_at",       String(50)),
    Column("log_line_count",    Integer),
    Column("errors_json",       Text),
    Column("ingested_at",       DateTime, default=datetime.now),
    Column("analysis_done",     Boolean, default=False),
)

analyses_table = Table(
    "analyses", metadata,
    Column("id",                   Integer, primary_key=True, autoincrement=True),
    Column("build_id",             Integer, nullable=False),
    Column("predicted_category",   String(50)),
    Column("all_categories_json",  Text),
    Column("severity",             String(20)),
    Column("label",                String(255)),
    Column("recommendations_json", Text),
    Column("confidence_score",     Float),
    Column("probabilities_json",   Text),
    Column("model_used",           String(30)),
    Column("analysed_at",          DateTime, default=datetime.now),
)

flaky_tests_table = Table(
    "flaky_tests", metadata,
    Column("id",               Integer, primary_key=True, autoincrement=True),
    Column("scenario_name",    Text, nullable=False),
    Column("job_type",         String(50)),
    Column("total_runs",       Integer),
    Column("fail_count",       Integer),
    Column("pass_count",       Integer),
    Column("fail_rate",        Float),
    Column("alternation_rate", Float),
    Column("status",           String(30)),     # FLAKY | CONSISTENTLY_FAILING | STABLE_PASSING
    Column("run_history_json", Text),
    Column("computed_at",      DateTime, default=datetime.now),
)


def get_engine(db_path: str = "data/analysis.db") -> Engine:
    global _engine
    if _engine is None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{db_path}", echo=False)
        metadata.create_all(_engine)
    return _engine


def init_db(db_path: str = "data/analysis.db") -> Engine:
    return get_engine(db_path)


@contextmanager
def get_conn():
    engine = get_engine()
    with engine.connect() as conn:
        yield conn
        conn.commit()


# ── Build operations ──────────────────────────────────────────────────────────

def upsert_build(build_data: dict) -> int:
    with get_conn() as conn:
        existing = conn.execute(
            select(builds_table.c.id).where(
                builds_table.c.filename == build_data["filename"]
            )
        ).fetchone()
        if existing:
            conn.execute(
                update(builds_table)
                .where(builds_table.c.filename == build_data["filename"])
                .values(**{k: v for k, v in build_data.items() if k != "id"})
            )
            return existing[0]
        result = conn.execute(builds_table.insert().values(**build_data))
        return result.inserted_primary_key[0]


def get_build_by_id(build_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            select(builds_table).where(builds_table.c.id == build_id)
        ).fetchone()
    return dict(row._mapping) if row else None


def get_build_by_filename(filename: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            select(builds_table).where(builds_table.c.filename == filename)
        ).fetchone()
    return dict(row._mapping) if row else None


def list_builds(job_type=None, status=None, limit=100, offset=0) -> list[dict]:
    with get_conn() as conn:
        q = select(builds_table).order_by(builds_table.c.id.desc())
        if job_type:
            q = q.where(builds_table.c.job_type == job_type)
        if status:
            q = q.where(builds_table.c.status == status)
        q = q.limit(limit).offset(offset)
        rows = conn.execute(q).fetchall()
    return [dict(r._mapping) for r in rows]


def count_builds(job_type=None, status=None) -> int:
    from sqlalchemy import func
    with get_conn() as conn:
        q = select(func.count()).select_from(builds_table)
        if job_type:
            q = q.where(builds_table.c.job_type == job_type)
        if status:
            q = q.where(builds_table.c.status == status)
        return conn.execute(q).scalar() or 0


def mark_analysis_done(build_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            update(builds_table)
            .where(builds_table.c.id == build_id)
            .values(analysis_done=True)
        )


# ── Analysis operations ───────────────────────────────────────────────────────

def save_analysis(analysis_data: dict) -> int:
    with get_conn() as conn:
        result = conn.execute(analyses_table.insert().values(**analysis_data))
        return result.inserted_primary_key[0]


def get_analysis_by_build(build_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            select(analyses_table)
            .where(analyses_table.c.build_id == build_id)
            .order_by(analyses_table.c.id.desc())
        ).fetchone()
    return dict(row._mapping) if row else None


# ── Flaky tests operations ────────────────────────────────────────────────────

def save_flaky_results(flaky_list: list[dict]) -> None:
    with get_conn() as conn:
        conn.execute(flaky_tests_table.delete())   # replace with fresh batch
        for item in flaky_list:
            conn.execute(flaky_tests_table.insert().values(
                scenario_name=item["scenario_name"],
                job_type=item["job_type"],
                total_runs=item["total_runs"],
                fail_count=item["fail_count"],
                pass_count=item["pass_count"],
                fail_rate=item["fail_rate"],
                alternation_rate=item["alternation_rate"],
                status=item["status"],
                run_history_json=json.dumps(item.get("run_history", [])),
            ))


def list_flaky_tests(status: str | None = None, limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        q = select(flaky_tests_table).order_by(
            flaky_tests_table.c.alternation_rate.desc()
        )
        if status:
            q = q.where(flaky_tests_table.c.status == status)
        q = q.limit(limit)
        rows = conn.execute(q).fetchall()
    result = []
    for r in rows:
        d = dict(r._mapping)
        d["run_history"] = json.loads(d.pop("run_history_json", "[]"))
        result.append(d)
    return result


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    from sqlalchemy import func
    with get_conn() as conn:
        total = conn.execute(
            select(func.count()).select_from(builds_table)
        ).scalar() or 0
        by_status = conn.execute(
            select(builds_table.c.status, func.count().label("cnt"))
            .group_by(builds_table.c.status)
        ).fetchall()
        by_job = conn.execute(
            select(builds_table.c.job_type, func.count().label("cnt"))
            .group_by(builds_table.c.job_type)
        ).fetchall()
        by_category = conn.execute(
            select(analyses_table.c.predicted_category, func.count().label("cnt"))
            .group_by(analyses_table.c.predicted_category)
            .order_by(func.count().desc())
        ).fetchall()
        flaky_count = conn.execute(
            select(func.count()).select_from(flaky_tests_table)
            .where(flaky_tests_table.c.status == "FLAKY")
        ).scalar() or 0

    return {
        "total_builds":     total,
        "by_status":        {r[0]: r[1] for r in by_status},
        "by_job_type":      {r[0]: r[1] for r in by_job},
        "by_error_category":{r[0]: r[1] for r in by_category},
        "flaky_count":      flaky_count,
    }
