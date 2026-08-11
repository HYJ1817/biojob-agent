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
    StrictBool,
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
CandidateDecisionValue = Literal["pending", "kept", "ignored", "later", "error"]
SourceAdapterValue = Literal["manual", "public_page", "feed"]

NonBlank100 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
NonBlank200 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
LongText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=10_000),
]
JobDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100_000),
]
UrlText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_048),
]


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def reject_non_finite_json(cls, data: Any) -> Any:
        sanitized, found = _sanitize_non_finite(data)
        if not found:
            return data
        if isinstance(data, dict) and isinstance(sanitized, dict):
            data.clear()
            data.update(sanitized)
            raise ValueError("request body must not contain NaN or Infinity")
        if isinstance(data, list) and isinstance(sanitized, list):
            data[:] = sanitized
            raise ValueError("request body must not contain NaN or Infinity")
        # A model body must be an object. Returning the finite placeholder lets
        # Pydantic produce a JSON-safe structural 422 for a bare NaN body.
        return sanitized


class ProfileFactCreate(_RequestModel):
    category: NonBlank100
    fact_key: NonBlank200
    value: JsonValue
    source_type: NonBlank100
    source_ref: ShortText | None = None
    visibility: FactVisibilityValue


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
    deleted: StrictBool | None = None

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


class CandidateImport(_RequestModel):
    company_name: NonBlank200
    title: NonBlank200
    detail_url: UrlText
    city: ShortText | None = None
    jd_text: JobDescription | None = None
    apply_url: UrlText | None = None
    careers_url: UrlText | None = None
    external_id: ShortText | None = None
    published_at: ShortText | None = None
    deadline_at: ShortText | None = None
    recruitment_type: ShortText | None = None

    @field_validator("detail_url", "apply_url", "careers_url", mode="before")
    @classmethod
    def validate_urls(cls, value: object) -> object:
        return _validate_url(value)


class CandidateDecisionRequest(_RequestModel):
    decision: CandidateDecisionValue
    note: Annotated[str, Field(max_length=10_000)] | None = None

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class SourceCreate(_RequestModel):
    name: NonBlank200
    adapter_type: SourceAdapterValue
    config: dict[str, JsonValue]
    enabled: StrictBool = True
    description: Annotated[str, Field(max_length=2_000)] | None = None

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class SourcePatch(_RequestModel):
    name: NonBlank200 | None = None
    config: dict[str, JsonValue] | None = None
    enabled: StrictBool | None = None
    description: Annotated[str, Field(max_length=2_000)] | None = None

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def require_field(self) -> "SourcePatch":
        if not self.model_fields_set:
            raise ValueError("source patch must include at least one field")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("source patch fields must not be null")
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
