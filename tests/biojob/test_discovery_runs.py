from __future__ import annotations

from contextlib import closing
import json

import pytest

from biojob.database import BioJobDatabase
from biojob.domain import (
    DomainConflictError,
    DomainDataCorruptionError,
    DomainNotFoundError,
    DomainValidationError,
    RawJob,
)
from biojob.service import BioJobService
from biojob.sources.catalog import DEFAULT_SOURCES, reviewed_hosts_for_source


@pytest.fixture
def database(tmp_path):
    database = BioJobDatabase(tmp_path / "biojob.db")
    database.initialize()
    return database


@pytest.fixture
def service(database):
    return BioJobService(database, source_adapters={})


class StaticAdapter:
    adapter_type = "static"

    def __init__(self, items):
        self.items = items

    def fetch(self, config):
        return self.items


class FailingAdapter:
    adapter_type = "failing"

    def fetch(self, config):
        raise RuntimeError("synthetic source outage\nprivate detail")


class InvalidReturnAdapter:
    adapter_type = "invalid_return"

    def fetch(self, config):
        return None


class CapturingAdapter:
    adapter_type = "search_feed"

    def __init__(self, items):
        self.items = items
        self.configs = []

    def fetch(self, config):
        self.configs.append(dict(config))
        return self.items


def raw_job(number=1):
    return RawJob(
        company_name="齐鲁制药",
        title=f"生物工艺工程师 {number}",
        detail_url=f"https://example.test/jobs/{number}",
        city="济南",
        jd_text="本科应届，负责发酵生产。",
        recruitment_type="校招",
    )


def test_default_catalog_covers_target_directions_regions_and_portals(service):
    sources = service.ensure_default_sources()

    discovery = [source for source in sources if source["adapter_type"] == "search_feed"]
    portals = [source for source in sources if source["adapter_type"] == "portal"]
    labels = " ".join(str(source["config"].get("query_label", "")) for source in discovery)

    assert len(discovery) >= 8
    assert all(source["enabled"] for source in discovery)
    assert all(term in labels for term in ("生产工艺", "QA QC", "细胞实验", "发酵微生物"))
    assert "山东" in labels
    assert "大城市" in labels
    assert "高校就业网" in labels
    assert "重点企业" in labels
    assert len(portals) >= 5
    assert all(not source["enabled"] for source in portals)
    assert all(source["config"]["url"].startswith("https://") for source in sources)
    assert all("database" not in source for source in sources)
    assert len(sources) == len(DEFAULT_SOURCES)
    assert all(reviewed_hosts_for_source(source["id"]) for source in discovery)


def test_default_upsert_is_idempotent_and_preserves_user_changes(service):
    original = service.ensure_default_sources()
    qilu = next(source for source in original if source["name"] == "齐鲁制药招聘")
    service.update_source(
        qilu["id"],
        enabled=False,
        config={
            "url": "https://jobs.example.test/qilu",
            "company_name": "齐鲁制药",
        },
        actor="user",
    )

    repeated = service.ensure_default_sources()
    updated = next(source for source in repeated if source["id"] == qilu["id"])

    assert len(repeated) == len(DEFAULT_SOURCES)
    assert updated["enabled"] is False
    assert updated["config"]["url"] == "https://jobs.example.test/qilu"


def test_default_upsert_tolerates_user_renaming_stable_default(service):
    original = service.ensure_default_sources()
    qilu = next(source for source in original if source["name"] == "齐鲁制药招聘")
    service.update_source(qilu["id"], name="我的齐鲁关注", actor="user")

    repeated = service.ensure_default_sources()

    assert len(repeated) == len(DEFAULT_SOURCES)
    assert (
        next(source for source in repeated if source["id"] == qilu["id"])["name"]
        == "我的齐鲁关注"
    )


def test_untouched_legacy_default_becomes_portal_without_losing_run_history(
    database, service
):
    now = "2026-08-12T00:00:00+00:00"
    with closing(database.connect()) as connection:
        connection.execute(
            "INSERT INTO sources "
            "(id, name, adapter_type, enabled, config_json, description, created_at, updated_at) "
            "VALUES (?, ?, 'public_page', 1, ?, ?, ?, ?)",
            (
                "default-qilu",
                "齐鲁制药招聘",
                json.dumps({
                    "url": "https://www.qilu-pharma.com/position.html",
                    "company_name": "齐鲁制药",
                }),
                "旧版自动抓取",
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO source_runs "
            "(id, source_id, status, cursor_json, result_count, started_at, finished_at) "
            "VALUES ('legacy-run', 'default-qilu', 'completed', '{}', 0, ?, ?)",
            (now, now),
        )

    sources = service.ensure_default_sources()
    qilu = next(source for source in sources if source["id"] == "default-qilu")

    assert qilu["adapter_type"] == "portal"
    assert qilu["enabled"] is False
    assert service.list_source_runs(source_id="default-qilu")[0]["id"] == "legacy-run"


def test_user_modified_legacy_default_is_not_reconciled(database, service):
    now = "2026-08-12T00:00:00+00:00"
    with closing(database.connect()) as connection:
        connection.execute(
            "INSERT INTO sources "
            "(id, name, adapter_type, enabled, config_json, description, created_at, updated_at) "
            "VALUES ('default-qilu', '我的齐鲁关注', 'public_page', 1, ?, '', ?, ?)",
            (json.dumps({"url": "https://jobs.example.test/qilu"}), now, now),
        )
        connection.execute(
            "INSERT INTO audit_log "
            "(id, action, entity_type, entity_id, actor, metadata_json, created_at) "
            "VALUES ('audit-user', 'source.updated', 'source', 'default-qilu', "
            "'user', '{}', ?)",
            (now,),
        )

    sources = service.ensure_default_sources()
    qilu = next(source for source in sources if source["id"] == "default-qilu")

    assert qilu["name"] == "我的齐鲁关注"
    assert qilu["adapter_type"] == "public_page"
    assert qilu["enabled"] is True


def test_reviewed_hosts_are_injected_for_run_but_never_persisted(database):
    adapter = CapturingAdapter([])
    service = BioJobService(database, source_adapters={"search_feed": adapter})
    source = next(
        item
        for item in service.ensure_default_sources()
        if item["id"] == "search-production-process"
    )

    assert service.run_source(source["id"], actor="user")["status"] == "completed"

    assert adapter.configs[0]["_reviewed_hosts"] == ["www.bing.com"]
    persisted = next(
        item for item in service.list_sources() if item["id"] == source["id"]
    )
    assert "_reviewed_hosts" not in persisted["config"]


def test_run_enabled_sources_returns_batch_summary_with_merged_results(database):
    duplicate = raw_job()
    adapter = CapturingAdapter([duplicate])
    service = BioJobService(
        database,
        source_adapters={"search_feed": adapter, "failing": FailingAdapter()},
    )
    for number in (1, 2):
        service.create_source(
            name=f"搜索源 {number}",
            adapter_type="search_feed",
            config={
                "url": f"https://search.example.test/{number}",
                "query_label": "测试",
            },
            actor="user",
        )
    service.create_source(
        name="失败来源", adapter_type="failing", config={}, actor="user"
    )

    result = service.run_enabled_sources(actor="user")

    assert {run["status"] for run in result["runs"]} == {"completed", "failed"}
    assert result["summary"] == {
        "completed_sources": 2,
        "failed_sources": 1,
        "new_candidates": 1,
        "merged_results": 1,
        "pending_verification": 1,
    }


def test_create_update_and_list_source_are_audited(service):
    created = service.create_source(
        name="企业招聘页",
        adapter_type="public_page",
        config={
            "url": "https://jobs.example.test/careers",
            "company_name": "测试生物",
        },
        actor="user",
    )
    updated = service.update_source(created["id"], enabled=False, actor="user")

    assert created["enabled"] is True
    assert updated["enabled"] is False
    assert service.list_sources() == [updated]
    assert [
        item["action"] for item in service.list_audit_log(entity_id=created["id"])
    ] == ["source.created", "source.updated"]


@pytest.mark.parametrize(
    "adapter_type,config",
    [
        ("unknown", {}),
        ("public_page", {"url": "https://jobs.example.test", "api_key": "x"}),
        ("public_page", {"url": "file:///C:/resume.docx"}),
        ("public_page", {"url": "https://user:pass@example.test/jobs"}),
        ("manual", {"path": "C:/jobs.json"}),
    ],
)
def test_source_registry_and_config_are_strict(service, adapter_type, config):
    with pytest.raises(DomainValidationError):
        service.create_source(
            name="不安全来源",
            adapter_type=adapter_type,
            config=config,
            actor="user",
        )


def test_run_source_ingests_valid_siblings_and_records_item_error(database):
    service = BioJobService(
        database,
        source_adapters={"static": StaticAdapter([raw_job(1), object(), raw_job(2)])},
    )
    source = service.create_source(
        name="静态测试来源", adapter_type="static", config={}, actor="user"
    )

    run = service.run_source(source["id"], actor="user")

    assert run["status"] == "completed"
    assert run["result_count"] == 2
    assert "1 item" in run["error_summary"]
    assert len(service.list_candidates()) == 2
    assert service.list_sources()[0]["health_status"] == "degraded"
    assert service.list_source_runs() == [run]
    assert service.list_source_runs(source_id=source["id"]) == [run]


def test_adapter_failure_is_isolated_and_other_source_remains_runnable(database):
    service = BioJobService(
        database,
        source_adapters={
            "failing": FailingAdapter(),
            "static": StaticAdapter([raw_job()]),
        },
    )
    failed_source = service.create_source(
        name="失败来源", adapter_type="failing", config={}, actor="user"
    )
    good_source = service.create_source(
        name="正常来源", adapter_type="static", config={}, actor="user"
    )

    failed = service.run_source(failed_source["id"], actor="user")
    completed = service.run_source(good_source["id"], actor="user")

    assert failed["status"] == "failed"
    assert failed["result_count"] == 0
    assert "synthetic source outage private detail" == failed["error_summary"]
    assert completed["status"] == "completed"
    health = {
        source["name"]: source["health_status"] for source in service.list_sources()
    }
    assert health == {"失败来源": "failed", "正常来源": "healthy"}


def test_invalid_adapter_result_finishes_failed_run(database):
    service = BioJobService(
        database, source_adapters={"invalid_return": InvalidReturnAdapter()}
    )
    source = service.create_source(
        name="返回值错误来源", adapter_type="invalid_return", config={}, actor="user"
    )

    run = service.run_source(source["id"], actor="user")

    assert run["status"] == "failed"
    assert "list" in run["error_summary"]


def test_source_failure_summary_redacts_credentials(database):
    class SecretFailingAdapter:
        adapter_type = "secret_failure"

        def fetch(self, config):
            raise RuntimeError(
                "Authorization: Bearer-secret password=hunter2 "
                "https://user:pass@example.test/jobs"
            )

    service = BioJobService(
        database, source_adapters={"secret_failure": SecretFailingAdapter()}
    )
    source = service.create_source(
        name="脱敏失败来源", adapter_type="secret_failure", config={}, actor="user"
    )

    summary = service.run_source(source["id"], actor="user")["error_summary"]

    assert "hunter2" not in summary
    assert "Bearer-secret" not in summary
    assert "user:pass" not in summary
    assert "<redacted>" in summary


def test_fetch_does_not_hold_sqlite_write_transaction(database):
    class LockProbeAdapter:
        adapter_type = "lock_probe"

        def fetch(self, config):
            with closing(database.connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("ROLLBACK")
            return [raw_job()]

    service = BioJobService(
        database, source_adapters={"lock_probe": LockProbeAdapter()}
    )
    source = service.create_source(
        name="锁探针", adapter_type="lock_probe", config={}, actor="user"
    )

    assert service.run_source(source["id"], actor="user")["status"] == "completed"


def test_disabled_and_missing_sources_cannot_run(service):
    source = service.create_source(
        name="手工来源", adapter_type="manual", config={}, actor="user"
    )
    service.update_source(source["id"], enabled=False, actor="user")

    with pytest.raises(DomainConflictError):
        service.run_source(source["id"], actor="user")
    with pytest.raises(DomainNotFoundError):
        service.run_source("missing-source", actor="user")


def test_run_enabled_sources_continues_after_failure(database):
    service = BioJobService(
        database,
        source_adapters={
            "failing": FailingAdapter(),
            "static": StaticAdapter([raw_job()]),
        },
    )
    service.create_source(
        name="失败来源", adapter_type="failing", config={}, actor="user"
    )
    service.create_source(
        name="正常来源", adapter_type="static", config={}, actor="user"
    )

    result = service.run_enabled_sources(actor="user")

    assert {run["status"] for run in result["runs"]} == {"failed", "completed"}


@pytest.mark.parametrize("target", ["config", "run_cursor", "run_status"])
def test_corrupt_source_state_fails_closed(database, service, target):
    source = service.create_source(
        name="待破坏来源", adapter_type="manual", config={}, actor="user"
    )
    if target != "config":
        run = service.run_source(source["id"], actor="user")
    with closing(database.connect()) as connection:
        if target == "config":
            connection.execute(
                "UPDATE sources SET config_json = 'NaN' WHERE id = ?", (source["id"],)
            )
        elif target == "run_cursor":
            connection.execute(
                "UPDATE source_runs SET cursor_json = 'NaN' WHERE id = ?", (run["id"],)
            )
        else:
            connection.execute("PRAGMA ignore_check_constraints=ON")
            connection.execute(
                "UPDATE source_runs SET status = 'surprise' WHERE id = ?", (run["id"],)
            )

    with pytest.raises(DomainDataCorruptionError):
        if target == "config":
            service.list_sources()
        else:
            service.list_source_runs()


def test_persisted_credential_shaped_source_config_fails_closed(database, service):
    source = service.create_source(
        name="安全配置来源",
        adapter_type="public_page",
        config={"url": "https://jobs.example.test"},
        actor="user",
    )
    with closing(database.connect()) as connection:
        connection.execute(
            "UPDATE sources SET config_json = ? WHERE id = ?",
            ('{"url":"https://jobs.example.test","api_key":"secret"}', source["id"]),
        )

    with pytest.raises(DomainDataCorruptionError):
        service.list_sources()
