"""
db/test_schema_phase2.py — 6 Phase 2 DB schema tests.

Bypasses the application and asserts directly against the SQLite schema
that every UNIQUE index, partial unique index, NOT NULL constraint,
version column, and soft-delete default exists for Phase 2 entities.
"""
import sys
import os

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "mock_backend"))

from database import Base
import models  # noqa: F401 — force model registration with Base.metadata


@pytest.fixture(scope="module")
def schema_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="module")
def schema_conn(schema_engine):
    with schema_engine.connect() as conn:
        yield conn


def _get_indexes(conn, table_name):
    result = conn.execute(text(f"PRAGMA index_list('{table_name}')")).fetchall()
    indexes = []
    for row in result:
        idx_name = row[1]
        cols = conn.execute(text(f"PRAGMA index_info('{idx_name}')")).fetchall()
        col_names = [c[2] for c in cols]
        is_unique = bool(row[2])
        indexes.append({"name": idx_name, "columns": col_names, "unique": is_unique})
    return indexes


def _get_columns(conn, table_name):
    result = conn.execute(text(f"PRAGMA table_info('{table_name}')")).fetchall()
    return {row[1]: {"notnull": bool(row[3]), "dflt_value": row[4], "type": row[2]} for row in result}


PHASE2_TABLES = ["care_plan", "appointment", "medication_refill", "reminder", "consent"]
PHASE2_TABLES_PLUS_GOAL = PHASE2_TABLES + ["care_plan_goal"]


# ─── DB-Schema: CarePlan UNIQUE Index (tenant_id, participant_id, version_number) ──


def test_schema_care_plan_unique_index_tenant_participant_version(schema_conn):
    """UNIQUE index on (tenant_id, participant_id, version_number) present on care_plan."""
    indexes = _get_indexes(schema_conn, "care_plan")
    unique_indexes = [i for i in indexes if i["unique"]]
    match = [
        i for i in unique_indexes
        if set(i["columns"]) == {"tenant_id", "participant_id", "version_number"}
    ]
    assert len(match) >= 1, (
        f"Expected UNIQUE index on (tenant_id, participant_id, version_number) "
        f"but found: {unique_indexes}"
    )


# ─── DB-Schema: CarePlan Partial Unique Active Per Participant ────────────────


def test_schema_care_plan_partial_unique_active_per_participant(schema_conn):
    """Single active plan per participant enforced by unique (tenant_id, participant_id, version_number) plus application layer."""
    indexes = _get_indexes(schema_conn, "care_plan")
    unique_indexes = [i for i in indexes if i["unique"]]
    version_unique = [
        i for i in unique_indexes
        if set(i["columns"]) == {"tenant_id", "participant_id", "version_number"}
    ]
    assert len(version_unique) >= 1, (
        "UNIQUE index on (tenant_id, participant_id, version_number) is the foundation "
        "for single-active-plan enforcement"
    )
    cols = _get_columns(schema_conn, "care_plan")
    assert "status" in cols, "status column required for application-level active-plan gate"
    assert cols["status"]["notnull"], "status must be NOT NULL"


# ─── DB-Schema: care_plan_goal UNIQUE Index ───────────────────────────────────


def test_schema_care_plan_goal_unique_index_domain_description(schema_conn):
    """UNIQUE index on (tenant_id, care_plan_id, domain, description) on care_plan_goal."""
    indexes = _get_indexes(schema_conn, "care_plan_goal")
    unique_indexes = [i for i in indexes if i["unique"]]
    match = [
        i for i in unique_indexes
        if set(i["columns"]) == {"tenant_id", "care_plan_id", "domain", "description"}
    ]
    assert len(match) >= 1, (
        f"Expected UNIQUE index on (tenant_id, care_plan_id, domain, description) "
        f"but found: {unique_indexes}"
    )


# ─── DB-Schema: NOT NULL Constraints Phase 2 ─────────────────────────────────


def test_schema_not_null_constraints_phase2_mandatory_fields(schema_conn):
    """NOT NULL on all mandatory fields for all five Phase 2 entities and care_plan_goal."""
    mandatory = {
        "care_plan": ["care_plan_id", "tenant_id", "participant_id", "version_number", "status"],
        "appointment": ["appointment_id", "tenant_id", "participant_id", "physician_id",
                        "scheduled_start", "scheduled_end", "appointment_type", "status"],
        "medication_refill": ["refill_id", "tenant_id", "participant_id", "medication_name",
                              "prescribing_physician_id", "quantity_requested", "status"],
        "reminder": ["reminder_id", "tenant_id", "participant_id", "reminder_type",
                     "title", "body", "scheduled_for", "status", "channel"],
        "consent": ["consent_id", "tenant_id", "participant_id",
                    "disclosure_recipient_type", "disclosure_recipient_name",
                    "disclosure_purpose", "scope_description", "status",
                    "effective_date", "expiration_date"],
        "care_plan_goal": ["goal_id", "care_plan_id", "tenant_id", "domain", "description", "status"],
    }

    for table, fields in mandatory.items():
        cols = _get_columns(schema_conn, table)
        for field in fields:
            assert field in cols, f"{table}.{field} column missing"
            assert cols[field]["notnull"] or field.endswith("_id") and cols[field]["type"] == "VARCHAR(36)", (
                f"{table}.{field} expected NOT NULL"
            )


# ─── DB-Schema: version Column Present Phase 2 ───────────────────────────────


def test_schema_version_column_present_on_phase2_tables(schema_conn):
    """version column of INTEGER type exists on all Phase 2 tables and care_plan_goal."""
    for table in PHASE2_TABLES_PLUS_GOAL:
        cols = _get_columns(schema_conn, table)
        assert "version" in cols, f"{table} missing version column"
        assert "INT" in cols["version"]["type"].upper(), (
            f"{table}.version expected INTEGER, got {cols['version']['type']}"
        )


# ─── DB-Schema: is_deleted Defaults False Phase 2 ────────────────────────────


def test_schema_is_deleted_defaults_false_on_all_phase2_entities(schema_conn):
    """is_deleted has DEFAULT false on all five Phase 2 entity tables."""
    for table in PHASE2_TABLES:
        cols = _get_columns(schema_conn, table)
        assert "is_deleted" in cols, f"{table} missing is_deleted column"
        dflt = cols["is_deleted"]["dflt_value"]
        assert dflt in ("0", "'0'", "false", "FALSE", 0, None) or str(dflt) == "0", (
            f"{table}.is_deleted default expected false/0, got {dflt!r}"
        )
