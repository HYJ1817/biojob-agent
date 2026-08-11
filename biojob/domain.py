"""Domain values and errors for BioJob."""

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


class DomainValidationError(ValueError):
    """Raised when a domain operation receives invalid input."""


class DomainConflictError(ValueError):
    """Raised when a domain uniqueness or state invariant conflicts."""


class DomainDataCorruptionError(RuntimeError):
    """Raised when persisted domain data cannot be decoded safely."""


class DomainNotFoundError(LookupError):
    """Raised when a requested domain entity does not exist."""
