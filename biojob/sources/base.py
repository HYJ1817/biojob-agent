"""Contracts and errors shared by BioJob discovery sources."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from biojob.domain import RawJob


class SourceAdapterError(RuntimeError):
    """Base error for a source fetch or parse failure."""


class SourceConfigurationError(ValueError):
    """Raised when persisted or user-supplied source config is invalid."""


class SourceSecurityError(SourceAdapterError):
    """Raised when a source attempts a prohibited network or parser action."""


class SourceFetchError(SourceAdapterError):
    """Raised when a bounded fetch or response validation fails."""


class JobSourceAdapter(Protocol):
    """Synchronous adapter contract used by discovery worker threads."""

    adapter_type: str

    def fetch(self, config: Mapping[str, object]) -> list[RawJob]: ...


def require_config_string(
    config: Mapping[str, object], key: str, *, optional: bool = False
) -> str | None:
    value = config.get(key)
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip():
        suffix = " or omitted" if optional else ""
        raise SourceConfigurationError(f"{key} must be a non-empty string{suffix}")
    return value.strip()
