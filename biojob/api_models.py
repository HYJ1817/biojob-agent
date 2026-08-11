"""Validated request models for the local BioJob HTTP API."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StringConstraints,
    field_validator,
    model_validator,
)


ApplicationStatusValue = Literal[
    "considering",
    "preparing",
    "applied",
    "assessment",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
    "expired",
]
FactStatusValue = Literal["pending", "confirmed", "rejected", "conflicted"]
FactVisibilityValue = Literal["matching", "resume", "both", "private"]
LifecycleStatusValue = Literal["open", "closed", "unknown"]

NonBlank100 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
NonBlank200 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=10_000)]
JobDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=100_000),
]
UrlText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2_048)]


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileFactCreate(_RequestModel):
    category: NonBlank100
    fact_key: NonBlank200
    value: JsonValue
    source_type: NonBlank100
    source_ref: ShortText | None = None
    visibility: FactVisibilityValue

    @model_validator(mode="before")
    @classmethod
    def value_must_be_finite(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "value" not in data:
            return data
        sanitized, found = _sanitize_non_finite(data["value"])
        if found:
            # FastAPI includes rejected input in its 422 envelope. Replace the
            # non-standard floats before raising so encoding that envelope does
            # not itself fail and turn a client error into a 500 response.
            data["value"] = sanitized
            raise ValueError("value must not contain NaN or Infinity")
        return data


class ProfileFactPatch(_RequestModel):
    status: FactStatusValue | None = None

    @model_validator(mode="after")
    def require_status(self) -> "ProfileFactPatch":
        if "status" not in self.model_fields_set or self.status is None:
            raise ValueError("profile fact patch must include status")
        return self


class JobCreate(_RequestModel):
    company_name: NonBlank200
    title: NonBlank200
    city: ShortText | None = None
    detail_url: UrlText | None = None
    apply_url: UrlText | None = None
    careers_url: UrlText | None = None
    direction: ShortText | None = None
    recruitment_type: ShortText | None = None
    education_requirement: ShortText | None = None
    major_requirement: ShortText | None = None
    jd_text: JobDescription | None = None
    published_at: ShortText | None = None
    deadline_at: ShortText | None = None
    lifecycle_status: LifecycleStatusValue = "unknown"
    notes: LongText = ""
    company_type: ShortText | None = None
    company_city: ShortText | None = None
    next_follow_up_at: ShortText | None = None
    application_notes: LongText = ""

    @field_validator("detail_url", "apply_url", "careers_url", mode="before")
    @classmethod
    def validate_urls(cls, value: object) -> object:
        return _validate_url(value)

    @field_validator("next_follow_up_at")
    @classmethod
    def validate_follow_up(cls, value: str | None) -> str | None:
        return _validate_aware_datetime(value)


class JobPatch(_RequestModel):
    notes: Annotated[str, Field(max_length=10_000)] | None = None
    next_follow_up_at: ShortText | None = None
    lifecycle_status: LifecycleStatusValue | None = None
    application_status: ApplicationStatusValue | None = None
    deleted: bool | None = None

    @field_validator("notes")
    @classmethod
    def strip_notes(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("next_follow_up_at")
    @classmethod
    def validate_follow_up(cls, value: str | None) -> str | None:
        return _validate_aware_datetime(value)

    @model_validator(mode="after")
    def validate_patch_shape(self) -> "JobPatch":
        provided = self.model_fields_set
        if not provided:
            raise ValueError("job patch must include at least one field")
        if "deleted" in provided:
            if self.deleted is not True:
                raise ValueError("deleted must be true")
            if provided != {"deleted"}:
                raise ValueError("deleted cannot be combined with other fields")
        return self


def _validate_url(value: object) -> object:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("URL must not contain control characters")
    stripped = value.strip()
    try:
        parsed = urlsplit(stripped)
        host = parsed.hostname
        parsed.port
    except ValueError:
        raise ValueError("URL must be an absolute http or https URL") from None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("URL must be an absolute http or https URL")
    return stripped


def _validate_aware_datetime(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() is None:
            raise ValueError("timezone required")
    except (OverflowError, TypeError, ValueError):
        raise ValueError(
            "next_follow_up_at must be a timezone-aware ISO-8601 datetime"
        ) from None
    return value


def _sanitize_non_finite(value: Any) -> tuple[Any, bool]:
    if isinstance(value, float) and not math.isfinite(value):
        return None, True
    if isinstance(value, list):
        result = []
        found = False
        for item in value:
            sanitized, item_found = _sanitize_non_finite(item)
            result.append(sanitized)
            found = found or item_found
        return result, found
    if isinstance(value, dict):
        result = {}
        found = False
        for key, item in value.items():
            sanitized, item_found = _sanitize_non_finite(item)
            result[key] = sanitized
            found = found or item_found
        return result, found
    return value, False
