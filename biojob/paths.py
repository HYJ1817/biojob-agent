"""Profile-aware filesystem paths for BioJob data."""

from pathlib import Path

from hermes_constants import get_hermes_home


def biojob_data_dir() -> Path:
    """Return the BioJob data directory for the active Hermes profile."""
    return get_hermes_home() / "biojob"


def biojob_database_path() -> Path:
    """Return the SQLite database path for the active Hermes profile."""
    return biojob_data_dir() / "biojob.db"
