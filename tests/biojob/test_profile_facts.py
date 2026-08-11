from __future__ import annotations

from contextlib import closing
import json
import sqlite3
import threading

import pytest

import biojob.service as service_module
from biojob.database import BioJobDatabase
from biojob.domain import (
    DomainConflictError,
    DomainDataCorruptionError,
    DomainNotFoundError,
    DomainValidationError,
)
from biojob.repository import BioJobRepository
from biojob.service import BioJobService


@pytest.fixture
def database(tmp_path):
    database = BioJobDatabase(tmp_path / "biojob.db")
    database.initialize()
    return database


@pytest.fixture
def service(database):
    return BioJobService(database)


def create_fact(service, *, fact_key="cck8", visibility="both", value=None):
    return service.create_profile_fact(
        category="laboratory",
        fact_key=fact_key,
        value=value if value is not None else {"skill": "CCK-8细胞活性检测"},
        source_type="user",
        visibility=visibility,
        actor="user",
    )


def test_created_fact_is_pending_unconfirmed_and_audited(service):
    fact = create_fact(service)

    assert fact["status"] == "pending"
    assert fact["confirmed_at"] is None
    assert fact["value"] == {"skill": "CCK-8细胞活性检测"}
    assert "value_json" not in fact

    audit = service.list_audit_log(entity_id=fact["id"])
    assert [entry["action"] for entry in audit] == ["profile_fact.created"]
    assert audit[0]["metadata"]["status"] == "pending"
    assert "metadata_json" not in audit[0]


def test_unconfirmed_fact_is_excluded_from_both_purposes(service):
    create_fact(service)

    assert service.list_usable_facts("resume") == []
    assert service.list_usable_facts("matching") == []


def test_confirmation_makes_fact_usable_and_appends_exact_audit_action(service):
    fact = create_fact(service)

    confirmed = service.set_profile_fact_status(fact["id"], "confirmed", actor="user")

    assert confirmed["confirmed_at"] is not None
    assert [item["id"] for item in service.list_usable_facts("resume")] == [
        fact["id"]
    ]
    assert [item["id"] for item in service.list_usable_facts("matching")] == [
        fact["id"]
    ]
    audit = service.list_audit_log(entity_id=fact["id"])
    assert audit[-1]["action"] == "profile_fact.confirmed"
    assert audit[-1]["metadata"] == {
        "old_status": "pending",
        "new_status": "confirmed",
    }


def test_visibility_filtering_matrix(service):
    facts = {
        visibility: create_fact(
            service,
            fact_key=f"fact-{visibility}",
            visibility=visibility,
        )
        for visibility in ("resume", "matching", "both", "private")
    }
    for fact in facts.values():
        service.set_profile_fact_status(fact["id"], "confirmed", actor="user")

    assert {fact["visibility"] for fact in service.list_usable_facts("resume")} == {
        "resume",
        "both",
    }
    assert {
        fact["visibility"] for fact in service.list_usable_facts("matching")
    } == {"matching", "both"}


@pytest.mark.parametrize("status", ["pending", "rejected", "conflicted"])
def test_non_confirmed_statuses_are_never_usable(service, status):
    fact = create_fact(service, fact_key=f"fact-{status}")
    if status != "pending":
        service.set_profile_fact_status(fact["id"], status, actor="user")

    assert service.list_usable_facts("resume") == []
    assert service.list_usable_facts("matching") == []


def test_moving_away_from_confirmed_clears_confirmed_at(service):
    fact = create_fact(service)
    confirmed = service.set_profile_fact_status(fact["id"], "confirmed", actor="user")
    assert confirmed["confirmed_at"] is not None

    rejected = service.set_profile_fact_status(fact["id"], "rejected", actor="user")

    assert rejected["confirmed_at"] is None
    assert service.list_usable_facts("resume") == []
    assert service.list_audit_log(entity_id=fact["id"])[-1]["action"] == (
        "profile_fact.rejected"
    )


@pytest.mark.parametrize("visibility", ["public", "", None, 3])
def test_invalid_visibility_raises_domain_validation_error(service, visibility):
    with pytest.raises(DomainValidationError):
        create_fact(service, visibility=visibility)


@pytest.mark.parametrize("status", ["approved", "", None, 3])
def test_invalid_status_raises_domain_validation_error(service, status):
    fact = create_fact(service)

    with pytest.raises(DomainValidationError):
        service.set_profile_fact_status(fact["id"], status, actor="user")


@pytest.mark.parametrize("purpose", ["private", "both", "", None, 3, []])
def test_invalid_purpose_raises_domain_validation_error(service, purpose):
    with pytest.raises(DomainValidationError):
        service.list_usable_facts(purpose)


@pytest.mark.parametrize(
    "field,value",
    [
        ("category", ""),
        ("category", "   "),
        ("fact_key", None),
        ("source_type", 7),
        ("actor", ""),
    ],
)
def test_required_create_fields_must_be_nonempty_strings(service, field, value):
    arguments = {
        "category": "laboratory",
        "fact_key": "cck8",
        "value": {"skill": "CCK-8"},
        "source_type": "user",
        "visibility": "both",
        "actor": "user",
    }
    arguments[field] = value

    with pytest.raises(DomainValidationError):
        service.create_profile_fact(**arguments)


def test_non_json_serializable_value_raises_domain_validation_error(service):
    with pytest.raises(DomainValidationError):
        create_fact(service, value={"bad": object()})


def test_duplicate_fact_key_is_domain_conflict_without_extra_audit(service):
    first = create_fact(service)
    audit_count = len(service.list_audit_log())

    with pytest.raises(DomainConflictError) as exc_info:
        create_fact(service, value={"skill": "different"})

    assert exc_info.value.__cause__ is None
    assert len(service.list_audit_log()) == audit_count
    assert len(service.list_audit_log(entity_id=first["id"])) == 1


def test_status_change_for_missing_fact_raises_domain_not_found(service):
    with pytest.raises(DomainNotFoundError):
        service.set_profile_fact_status("missing-fact", "confirmed", actor="user")


def test_value_json_round_trips_nested_chinese_data(service):
    value = {
        "技能": "细胞培养",
        "details": {"assays": ["CCK-8", "流式细胞术"], "years": 2},
        "available": True,
    }

    fact = create_fact(service, value=value)
    service.set_profile_fact_status(fact["id"], "confirmed", actor="user")

    assert service.list_usable_facts("resume")[0]["value"] == value


def test_audit_failure_rolls_back_business_write_and_preserves_error(
    database,
    monkeypatch,
):
    def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(BioJobRepository, "insert_audit_log", fail_audit)
    service = BioJobService(database)

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        create_fact(service)

    with closing(database.connect()) as connection:
        assert connection.execute("SELECT COUNT(*) FROM profile_facts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_audit_log_has_stable_chronological_order(service):
    fact = create_fact(service)
    service.set_profile_fact_status(fact["id"], "confirmed", actor="user")
    service.set_profile_fact_status(fact["id"], "conflicted", actor="reviewer")

    audit = service.list_audit_log(entity_id=fact["id"])

    assert [entry["action"] for entry in audit] == [
        "profile_fact.created",
        "profile_fact.confirmed",
        "profile_fact.conflicted",
    ]
    assert [entry["created_at"] for entry in audit] == sorted(
        entry["created_at"] for entry in audit
    )


def test_status_timestamp_is_generated_after_write_lock(database, monkeypatch):
    service = BioJobService(database)
    fact = create_fact(service)
    older_connect_entered = threading.Event()
    release_older_connect = threading.Event()
    holder_has_lock = threading.Event()
    release_holder = threading.Event()
    older_begin_attempted = threading.Event()
    clock_lock = threading.Lock()
    timestamps = iter(
        [
            "2099-01-01T00:00:01+00:00",
            "2099-01-01T00:00:02+00:00",
        ]
    )
    real_connect = database.connect
    real_get = BioJobRepository.get_profile_fact
    results = {}
    errors = {}

    class SignalingConnection:
        def __init__(self, delegate):
            self._delegate = delegate

        def execute(self, sql, *args):
            if sql.strip().upper() == "BEGIN IMMEDIATE":
                older_begin_attempted.set()
            return self._delegate.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self._delegate, name)

    def controlled_connect():
        connection = real_connect()
        if threading.current_thread().name != "older-blocked":
            return connection
        older_connect_entered.set()
        if not release_older_connect.wait(timeout=5):
            connection.close()
            raise TimeoutError("older writer was not released")
        return SignalingConnection(connection)

    def controlled_get(repository, fact_id):
        row = real_get(repository, fact_id)
        if threading.current_thread().name == "newer-lock-holder":
            holder_has_lock.set()
            if not release_holder.wait(timeout=5):
                raise TimeoutError("lock holder was not released")
        return row

    def controlled_now():
        with clock_lock:
            return next(timestamps)

    def change_status(label, status):
        try:
            results[label] = service.set_profile_fact_status(
                fact["id"], status, actor=label
            )
        except Exception as exc:
            errors[label] = exc

    monkeypatch.setattr(database, "connect", controlled_connect)
    monkeypatch.setattr(BioJobRepository, "get_profile_fact", controlled_get)
    monkeypatch.setattr(service_module, "_utc_now", controlled_now)

    older = threading.Thread(
        target=change_status,
        args=("older", "conflicted"),
        name="older-blocked",
    )
    holder = threading.Thread(
        target=change_status,
        args=("newer", "confirmed"),
        name="newer-lock-holder",
    )
    try:
        older.start()
        assert older_connect_entered.wait(timeout=5)
        holder.start()
        assert holder_has_lock.wait(timeout=5)
        release_older_connect.set()
        assert older_begin_attempted.wait(timeout=5)
        release_holder.set()
        holder.join(timeout=5)
        older.join(timeout=5)
    finally:
        release_older_connect.set()
        release_holder.set()
        if holder.ident is not None:
            holder.join(timeout=5)
        if older.ident is not None:
            older.join(timeout=5)

    assert not holder.is_alive()
    assert not older.is_alive()
    assert errors == {}
    audit = service.list_audit_log(entity_id=fact["id"])
    previous_status = "pending"
    for entry in audit[1:]:
        assert entry["metadata"]["old_status"] == previous_status
        previous_status = entry["metadata"]["new_status"]
    assert previous_status == "conflicted"
    assert results["older"]["updated_at"] == audit[-1]["created_at"]


def test_profile_fact_text_fields_are_stripped_before_storage_and_uniqueness(service):
    fact = service.create_profile_fact(
        category=" laboratory ",
        fact_key=" cck8 ",
        value={"skill": " keep surrounding value spaces "},
        source_type=" user ",
        source_ref=" resume:1 ",
        visibility=" both ",
        actor=" creator ",
    )

    assert fact["category"] == "laboratory"
    assert fact["fact_key"] == "cck8"
    assert fact["source_type"] == "user"
    assert fact["source_ref"] == "resume:1"
    assert fact["value"] == {"skill": " keep surrounding value spaces "}
    audit = service.list_audit_log(entity_id=fact["id"])
    assert audit[0]["actor"] == "creator"
    assert audit[0]["metadata"]["category"] == "laboratory"
    assert audit[0]["metadata"]["fact_key"] == "cck8"

    with pytest.raises(DomainConflictError):
        create_fact(service)


def test_status_visibility_and_purpose_use_consistent_stripping(service):
    fact = service.create_profile_fact(
        category="laboratory",
        fact_key="cck8",
        value={"skill": "CCK-8"},
        source_type="user",
        visibility=" both ",
        actor=" creator ",
    )

    service.set_profile_fact_status(fact["id"], " confirmed ", actor=" reviewer ")

    assert service.list_usable_facts(" resume ")[0]["id"] == fact["id"]
    assert service.list_audit_log(entity_id=fact["id"])[-1]["actor"] == "reviewer"


def test_audit_log_preserves_inserted_causality_for_equal_timestamps(
    database,
    service,
):
    fact = create_fact(service)
    inserted_events = (
        (
            "ffffffff-ffff-4fff-8fff-ffffffffffff",
            {"old_status": "pending", "new_status": "confirmed"},
        ),
        (
            "00000000-0000-4000-8000-000000000000",
            {"old_status": "confirmed", "new_status": "rejected"},
        ),
    )
    with closing(database.connect()) as connection:
        for audit_id, metadata in inserted_events:
            connection.execute(
                "INSERT INTO audit_log "
                "(id, action, entity_type, entity_id, actor, metadata_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    audit_id,
                    "profile_fact.probe",
                    "profile_fact",
                    fact["id"],
                    "tester",
                    json.dumps(metadata),
                    "2099-01-01T00:00:00+00:00",
                ),
            )

    audit = service.list_audit_log(entity_id=fact["id"])

    assert [entry["id"] for entry in audit[-2:]] == [
        audit_id for audit_id, _ in inserted_events
    ]
    previous_status = "pending"
    for entry in audit[-2:]:
        assert entry["metadata"]["old_status"] == previous_status
        previous_status = entry["metadata"]["new_status"]
        assert "rowid" not in entry
    assert previous_status == "rejected"


@pytest.mark.parametrize(
    "corrupt_json",
    [
        pytest.param(sqlite3.Binary(b"\xff"), id="invalid-utf8-blob"),
        pytest.param("NaN", id="nan"),
        pytest.param("Infinity", id="positive-infinity"),
        pytest.param("-Infinity", id="negative-infinity"),
        pytest.param("1e9999", id="positive-exponent-overflow"),
        pytest.param("-1e9999", id="negative-exponent-overflow"),
        pytest.param(
            '{"nested":{"value":1e9999}}',
            id="nested-exponent-overflow",
        ),
    ],
)
def test_corrupt_value_rolls_back_status_and_audit(
    database,
    service,
    corrupt_json,
):
    fact = create_fact(service)
    with closing(database.connect()) as connection:
        connection.execute(
            "UPDATE profile_facts SET value_json = ? WHERE id = ?",
            (corrupt_json, fact["id"]),
        )
    audit_count = len(service.list_audit_log(entity_id=fact["id"]))

    with pytest.raises(DomainDataCorruptionError) as exc_info:
        service.set_profile_fact_status(fact["id"], "confirmed", actor="reviewer")

    assert "profile_facts" in str(exc_info.value)
    assert fact["id"] in str(exc_info.value)
    assert "value_json" in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    with closing(database.connect()) as connection:
        stored = connection.execute(
            "SELECT status, confirmed_at FROM profile_facts WHERE id = ?",
            (fact["id"],),
        ).fetchone()
        stored_audit_count = connection.execute(
            "SELECT COUNT(*) FROM audit_log WHERE entity_id = ?",
            (fact["id"],),
        ).fetchone()[0]
    assert tuple(stored) == ("pending", None)
    assert stored_audit_count == audit_count


@pytest.mark.parametrize(
    "corrupt_json",
    [
        pytest.param("{not-json", id="syntax-error"),
        pytest.param('{"nested":[1e9999]}', id="nested-exponent-overflow"),
    ],
)
def test_usable_fact_list_reports_corrupt_entity_and_field(
    database,
    service,
    corrupt_json,
):
    fact = create_fact(service)
    service.set_profile_fact_status(fact["id"], "confirmed", actor="reviewer")
    with closing(database.connect()) as connection:
        connection.execute(
            "UPDATE profile_facts SET value_json = ? WHERE id = ?",
            (corrupt_json, fact["id"]),
        )

    with pytest.raises(DomainDataCorruptionError) as exc_info:
        service.list_usable_facts("resume")

    assert fact["id"] in str(exc_info.value)
    assert "profile_facts" in str(exc_info.value)
    assert "value_json" in str(exc_info.value)


def test_finite_floats_keep_float_semantics(service):
    value = {"score": 1.25, "nested": [-2.5e100, 0.0]}
    fact = create_fact(service, value=value)
    service.set_profile_fact_status(fact["id"], "confirmed", actor="reviewer")

    returned = service.list_usable_facts("resume")[0]["value"]

    assert returned == value
    assert isinstance(returned["score"], float)
    assert all(isinstance(item, float) for item in returned["nested"])


@pytest.mark.parametrize(
    "corrupt_json",
    [
        pytest.param(sqlite3.Binary(b"\xff"), id="invalid-utf8-blob"),
        pytest.param("NaN", id="nan"),
        pytest.param("Infinity", id="positive-infinity"),
        pytest.param("-Infinity", id="negative-infinity"),
    ],
)
def test_audit_list_reports_strict_json_corruption(
    database,
    service,
    corrupt_json,
):
    fact = create_fact(service)
    audit_id = service.list_audit_log(entity_id=fact["id"])[0]["id"]
    with closing(database.connect()) as connection:
        connection.execute(
            "UPDATE audit_log SET metadata_json = ? WHERE id = ?",
            (corrupt_json, audit_id),
        )

    with pytest.raises(DomainDataCorruptionError) as exc_info:
        service.list_audit_log(entity_id=fact["id"])

    assert "audit_log" in str(exc_info.value)
    assert audit_id in str(exc_info.value)
    assert "metadata_json" in str(exc_info.value)
    assert exc_info.value.__cause__ is None
