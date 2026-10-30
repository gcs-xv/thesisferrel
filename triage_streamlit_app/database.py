"""Database layer shared by local SQLite and deployed PostgreSQL."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import Column, Float, Index, Integer, MetaData, String, Table, Text, create_engine, select
from sqlalchemy.engine import Engine


metadata = MetaData()

episodes = Table(
    "episodes",
    metadata,
    Column("id_studi", String(80), primary_key=True),
    Column("contact_date", String(10)),
    Column("contact_time", String(8)),
    Column("initials", String(20)),
    Column("site", Integer),
    Column("unit", String(40)),
    Column("first_presentation", Integer),
    Column("age_years", Float),
    Column("sex", Integer),
    Column("temp", Float),
    Column("hr", Integer),
    Column("rr", Integer),
    Column("sbp", Integer),
    Column("dbp", Integer),
    Column("map", Float),
    Column("spo2", Integer),
    Column("oxygen", Integer),
    Column("oxygen_flow", Float),
    Column("oxygen_device", String(80)),
    Column("mentation", String(2)),
    Column("gcs", Integer),
    Column("rf_systemic", Integer),
    Column("rf_trismus", Integer),
    Column("rf_swallow", Integer),
    Column("rf_airway", Integer),
    Column("rf_spread", Integer),
    Column("rf_host", Integer),
    Column("rf_n_missing", Integer),
    Column("rf_score", Integer),
    Column("rf_airway_override", Integer),
    Column("rf_missing_reason", String(80)),
    Column("rf_missing_reason_other", Text),
    Column("clinical_risk", String(20)),
    Column("initial_plan", String(40)),
    Column("assessment_complete_time", String(8)),
    Column("predictor_window_violation", Integer),
    Column("form_a_complete", Integer),
    Column("form_a_saved_at", String(32)),
    Column("followup_date", String(10)),
    Column("followup_time", String(8)),
    Column("assessor", String(30)),
    Column("source_index_record", Integer),
    Column("source_receiving_record", Integer),
    Column("source_transfer_log", Integer),
    Column("source_receiving_contact", Integer),
    Column("outcome_complete", Integer),
    Column("urgent_source_control", Integer),
    Column("urgent_source_control_time", String(8)),
    Column("urgent_source_control_facility", Text),
    Column("advanced_airway", Integer),
    Column("advanced_airway_time", String(8)),
    Column("advanced_airway_facility", Text),
    Column("critical_care", Integer),
    Column("critical_care_time", String(8)),
    Column("critical_care_facility", Text),
    Column("death_odontogenic", Integer),
    Column("death_odontogenic_time", String(8)),
    Column("death_odontogenic_facility", Text),
    Column("outcome24_raw", Integer),
    Column("outcome24", Integer),
    Column("transfer24", Integer),
    Column("transfer_destination", Text),
    Column("transfer_time", String(8)),
    Column("transfer_reason_airway", Integer),
    Column("transfer_reason_sepsis", Integer),
    Column("transfer_reason_or_ga", Integer),
    Column("transfer_reason_no_icu", Integer),
    Column("transfer_reason_no_anesthesia_or", Integer),
    Column("transfer_reason_other", Integer),
    Column("transfer_reason_other_text", Text),
    Column("admission", Integer),
    Column("los_days", Float),
    Column("iv_antibiotic", Integer),
    Column("iv_antibiotic_time", String(8)),
    Column("bedside_drainage", Integer),
    Column("bedside_drainage_type", Text),
    Column("revisit7", Integer),
    Column("revisit7_date", String(10)),
    Column("adjudicator_a", Integer),
    Column("adjudicator_b", Integer),
    Column("adjudication_agreement", Integer),
    Column("final_decision", Integer),
    Column("form_b_complete", Integer),
    Column("form_b_saved_at", String(32)),
    Column("created_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False),
)

Index("idx_episodes_site", episodes.c.site)
Index("idx_episodes_outcome24", episodes.c.outcome24)


def normalize_database_url(url: str | None, app_dir: Path) -> str:
    if not url:
        return f"sqlite:///{(app_dir / 'triage_research.db').resolve()}"
    value = url.strip()
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+psycopg2://", 1)
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+psycopg2://", 1)
    return value


@lru_cache(maxsize=4)
def get_engine(database_url: str) -> Engine:
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(database_url, **kwargs)
    metadata.create_all(engine)
    return engine


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_episode(engine: Engine, id_studi: str) -> dict[str, Any] | None:
    with engine.connect() as connection:
        row = connection.execute(
            select(episodes).where(episodes.c.id_studi == id_studi)
        ).mappings().first()
    return dict(row) if row else None


def list_episode_ids(engine: Engine, *, require_form_a: bool = False) -> list[str]:
    statement = select(episodes.c.id_studi).order_by(episodes.c.id_studi)
    if require_form_a:
        statement = statement.where(episodes.c.form_a_complete == 1)
    with engine.connect() as connection:
        return list(connection.execute(statement).scalars())


def get_all_episodes(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        rows = connection.execute(
            select(episodes).order_by(episodes.c.contact_date, episodes.c.contact_time, episodes.c.id_studi)
        ).mappings()
        return [dict(row) for row in rows]


def upsert_episode(engine: Engine, data: dict[str, Any]) -> None:
    now = utc_now()
    valid_columns = set(episodes.c.keys())
    values = {key: value for key, value in data.items() if key in valid_columns}
    values["updated_at"] = now

    with engine.begin() as connection:
        exists = connection.execute(
            select(episodes.c.id_studi).where(episodes.c.id_studi == values["id_studi"])
        ).first()
        if exists:
            connection.execute(
                episodes.update()
                .where(episodes.c.id_studi == values["id_studi"])
                .values(**values)
            )
        else:
            values["created_at"] = now
            connection.execute(episodes.insert().values(**values))
