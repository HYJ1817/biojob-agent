"""Parameterized SQLite statements for BioJob domain services."""

from __future__ import annotations

import sqlite3


class BioJobRepository:
    """Execute BioJob SQL against a caller-owned connection and transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def insert_profile_fact(
        self,
        *,
        fact_id: str,
        category: str,
        fact_key: str,
        value_json: str,
        source_type: str,
        source_ref: str | None,
        status: str,
        visibility: str,
        confirmed_at: str | None,
        created_at: str,
        updated_at: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO profile_facts "
            "(id, category, fact_key, value_json, source_type, source_ref, status, "
            "visibility, confirmed_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fact_id,
                category,
                fact_key,
                value_json,
                source_type,
                source_ref,
                status,
                visibility,
                confirmed_at,
                created_at,
                updated_at,
            ),
        )

    def get_profile_fact(self, fact_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM profile_facts WHERE id = ?",
            (fact_id,),
        ).fetchone()

    def update_profile_fact_status(
        self,
        *,
        fact_id: str,
        status: str,
        confirmed_at: str | None,
        updated_at: str,
    ) -> int:
        cursor = self.connection.execute(
            "UPDATE profile_facts "
            "SET status = ?, confirmed_at = ?, updated_at = ? WHERE id = ?",
            (status, confirmed_at, updated_at, fact_id),
        )
        return cursor.rowcount

    def list_usable_profile_facts(
        self,
        *,
        status: str,
        first_visibility: str,
        second_visibility: str,
    ) -> list[sqlite3.Row]:
        return self.connection.execute(
            "SELECT * FROM profile_facts "
            "WHERE status = ? AND visibility IN (?, ?) "
            "ORDER BY created_at, id",
            (status, first_visibility, second_visibility),
        ).fetchall()

    def insert_audit_log(
        self,
        *,
        audit_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        actor: str,
        metadata_json: str,
        created_at: str,
    ) -> None:
        self.connection.execute(
            "INSERT INTO audit_log "
            "(id, action, entity_type, entity_id, actor, metadata_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                audit_id,
                action,
                entity_type,
                entity_id,
                actor,
                metadata_json,
                created_at,
            ),
        )

    def list_audit_log(self, entity_id: str | None = None) -> list[sqlite3.Row]:
        if entity_id is None:
            return self.connection.execute(
                "SELECT * FROM audit_log ORDER BY created_at, id"
            ).fetchall()
        return self.connection.execute(
            "SELECT * FROM audit_log "
            "WHERE entity_id = ? ORDER BY created_at, id",
            (entity_id,),
        ).fetchall()
