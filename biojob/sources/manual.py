"""Manual structured-job adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields

from biojob.domain import RawJob
from biojob.sources.base import SourceConfigurationError


_RAW_JOB_FIELDS = {field.name for field in fields(RawJob)}


class ManualJobAdapter:
    """Convert user-supplied structured rows without performing network I/O."""

    adapter_type = "manual"

    def fetch(self, config: Mapping[str, object]) -> list[RawJob]:
        jobs = config.get("jobs")
        if not isinstance(jobs, list):
            raise SourceConfigurationError("jobs must be a list")
        result: list[RawJob] = []
        for index, item in enumerate(jobs):
            if not isinstance(item, Mapping):
                raise SourceConfigurationError(f"jobs[{index}] must be an object")
            unknown = set(item) - _RAW_JOB_FIELDS
            if unknown:
                raise SourceConfigurationError(
                    f"jobs[{index}] has unsupported field: {sorted(unknown)[0]}"
                )
            try:
                result.append(RawJob(**dict(item)))
            except TypeError as exc:
                raise SourceConfigurationError(
                    f"jobs[{index}] is missing or has invalid fields"
                ) from exc
        return result
