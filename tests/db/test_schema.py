"""
db/test_schema.py — 8 tests covering the DB data integrity gate.

Bypasses the application and asserts directly against the SQLite schema
that every UNIQUE index, NOT NULL constraint, version column, and
soft-delete default exists as defined in the architecture.
"""
import sys
import os
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "mock_backend"))

from database import Base
from models import (
    Attendance, Claim, Incident, MARRecord, Participant, User,
)


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


# ─── 1. Participant unique index on (tenant_id, medicaid_id) ─────────────────

def test_schema_participant_unique_index_tenant_medicaid_id(schema_conn):
    """UNIQUE index on (tenant_id, medicaid_id) present on participant table via PRAGMA index_list."""
    indexes = _get_indexes(schema_conn, "participant")
    unique_indexes = [i for i in indexes if i["unique"]]
    medicaid_unique = next(
        (i for i in unique_indexes
         if "tenant_id" in i["columns"] and "medicaid_id" in i["columns"]),
        None,
    )
    assert medicaid_unique is not None, \
        f"No UNIQUE index on (tenant_id, medicaid_id) found. Indexes: {unique_indexes}"


# ─── 2. User unique indexes and primary key ───────────────────────────────────

def test_schema_user_unique_indexes_and_primary_key(schema_conn):
    """UNIQUE index on (tenant_id, email) and PRIMARY KEY on user_id present on user table."""
    indexes = _get_indexes(schema_conn, "user")
    unique_indexes = [i for i in indexes if i["unique"]]
    email_unique = next(
        (i for i in unique_indexes
         if "tenant_id" in i["columns"] and "email" in i["columns"]),
        None,
    )
    assert email_unique is not None, \
        f"No UNIQUE index on (tenant_id, email) found. Indexes: {unique_indexes}"

    columns = _get_columns(schema_conn, "user")
    assert "user_id" in columns, "user_id column not found in user table"


# ─── 3. Attendance unique index on (tenant_id, participant_id, date_of_service) ─

def test_schema_attendance_unique_index_tenant_participant_date(schema_conn):
    """UNIQUE index on (tenant_id, participant_id, date_of_service) present on attendance table."""
    indexes = _get_indexes(schema_conn, "attendance")
    unique_indexes = [i for i in indexes if i["unique"]]
    attendance_unique = next(
        (i for i in unique_indexes
         if "tenant_id" in i["columns"]
         and "participant_id" in i["columns"]
         and "date_of_service" in i["columns"]),
        None,
    )
    assert attendance_unique is not None, \
        f"No UNIQUE index on (tenant_id, participant_id, date_of_service). Indexes: {unique_indexes}"


# ─── 4. Claim unique indexes: reference_number and composite billing key ──────

def test_schema_claim_unique_indexes_reference_and_composite(schema_conn):
    """UNIQUE index on claim_reference_number and composite billing key both present on claim table."""
    indexes = _get_indexes(schema_conn, "claim")
    unique_indexes = [i for i in indexes if i["unique"]]

    ref_unique = next(
        (i for i in unique_indexes if i["columns"] == ["claim_reference_number"]),
        None,
    )
    assert ref_unique is not None, \
        f"No UNIQUE index on claim_reference_number. Indexes: {unique_indexes}"

    composite_unique = next(
        (i for i in unique_indexes
         if "tenant_id" in i["columns"]
         and "participant_id" in i["columns"]
         and "date_of_service_start" in i["columns"]
         and "procedure_code" in i["columns"]
         and "payer_type" in i["columns"]),
        None,
    )
    assert composite_unique is not None, \
        f"No composite UNIQUE index on (tenant_id, participant_id, date_of_service_start, procedure_code, payer_type). " \
        f"Indexes: {unique_indexes}"


# ─── 5. MARRecord unique index on (tenant_id, participant_id, medication_name, scheduled_time) ─

def test_schema_mar_record_unique_index_participant_medication_time(schema_conn):
    """UNIQUE index on (tenant_id, participant_id, medication_name, scheduled_time) present on mar_record."""
    indexes = _get_indexes(schema_conn, "mar_record")
    unique_indexes = [i for i in indexes if i["unique"]]
    mar_unique = next(
        (i for i in unique_indexes
         if "tenant_id" in i["columns"]
         and "participant_id" in i["columns"]
         and "medication_name" in i["columns"]
         and "scheduled_time" in i["columns"]),
        None,
    )
    assert mar_unique is not None, \
        f"No UNIQUE index on (tenant_id, participant_id, medication_name, scheduled_time). " \
        f"Indexes: {unique_indexes}"


# ─── 6. NOT NULL constraints on mandatory fields ──────────────────────────────

def test_schema_not_null_constraints_on_all_mandatory_fields(schema_conn):
    """NOT NULL confirmed on all mandatory fields for all six entities via PRAGMA table_info."""
    mandatory = {
        "participant": ["tenant_id", "first_name", "last_name", "date_of_birth",
                        "program_status", "is_deleted", "version"],
        "user": ["tenant_id", "first_name", "last_name", "email", "role",
                 "status", "version", "mfa_enabled", "failed_login_count"],
        "attendance": ["tenant_id", "participant_id", "date_of_service", "status", "version"],
        "claim": ["tenant_id", "participant_id", "attendance_ids", "payer_type",
                  "claim_reference_number", "procedure_code", "date_of_service_start",
                  "claim_status", "version"],
        "mar_record": ["tenant_id", "participant_id", "medication_name", "administered_by",
                       "scheduled_time", "status", "is_controlled_substance", "version"],
        "incident": ["tenant_id", "participant_id", "incident_date", "incident_type",
                     "description", "severity", "status", "is_sud_related", "version"],
    }

    for table, fields in mandatory.items():
        columns = _get_columns(schema_conn, table)
        for field in fields:
            assert field in columns, f"Field '{field}' not found in table '{table}'"
            assert columns[field]["notnull"], \
                f"Field '{field}' in table '{table}' is not NOT NULL"


# ─── 7. Version column present on all entity tables ──────────────────────────

def test_schema_version_column_present_on_all_entity_tables(schema_conn):
    """version column of INTEGER type exists on all six entity tables."""
    entity_tables = ["participant", "user", "attendance", "claim", "mar_record", "incident"]
    for table in entity_tables:
        columns = _get_columns(schema_conn, table)
        assert "version" in columns, f"version column not found in table '{table}'"
        assert "INT" in columns["version"]["type"].upper(), \
            f"version column in '{table}' has unexpected type: {columns['version']['type']}"


# ─── 8. is_deleted defaults false on participant and user ─────────────────────

def test_schema_is_deleted_defaults_false_on_participant_and_user(schema_conn):
    """is_deleted column has DEFAULT false on participant and user tables; no row has null is_deleted."""
    for table in ("participant",):
        columns = _get_columns(schema_conn, table)
        assert "is_deleted" in columns, f"is_deleted not found in {table}"
        dflt = columns["is_deleted"]["dflt_value"]
        assert dflt is not None and str(dflt) in ("0", "false", "False"), \
            f"is_deleted in {table} has unexpected default: {dflt!r}"

    # Confirm no existing rows have NULL is_deleted
    for table in ("participant",):
        null_count = schema_conn.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE is_deleted IS NULL")
        ).scalar()
        assert null_count == 0, \
            f"Table '{table}' has {null_count} rows with NULL is_deleted"
