from __future__ import annotations

from contextlib import closing

import pytest

from biojob.database import BioJobDatabase
from biojob.domain import (
    DomainConflictError,
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
