"""Domain values and errors for BioJob."""

from dataclasses import dataclass
from enum import StrEnum


class ProfileFactStatus(StrEnum):
    """Review state for a personal profile fact."""

    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CONFLICTED = "conflicted"


class FactVisibility(StrEnum):
    """Consumers allowed to use a confirmed profile fact."""

    MATCHING = "matching"
    RESUME = "resume"
    BOTH = "both"
    PRIVATE = "private"


class ApplicationStatus(StrEnum):
    """Auditable lifecycle state for a job application."""

    CONSIDERING = "considering"
    PREPARING = "preparing"
    APPLIED = "applied"
    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"


class CandidateDecision(StrEnum):
    """Latest review decision for a discovered job candidate."""

    PENDING = "pending"
    KEPT = "kept"
    IGNORED = "ignored"
    LATER = "later"
    ERROR = "error"


@dataclass(frozen=True)
class RawJob:
    """Untrusted job data returned by a source adapter."""

    company_name: str
    title: str
    detail_url: str
    city: str | None = None
    jd_text: str | None = None
    apply_url: str | None = None
    careers_url: str | None = None
    external_id: str | None = None
    published_at: str | None = None
    deadline_at: str | None = None
    recruitment_type: str | None = None


class DomainValidationError(ValueError):
    """Raised when a domain operation receives invalid input."""


class DomainConflictError(ValueError):
    """Raised when a domain uniqueness or state invariant conflicts."""


class DomainDataCorruptionError(RuntimeError):
    """Raised when persisted domain data cannot be decoded safely."""


class DomainNotFoundError(LookupError):
    """Raised when a requested domain entity does not exist."""
