"""Database layer for PatchSorter.

This module exposes the lightweight utilities in ``patchsorter.db.utils``
and re-exports the head/worker client packages.
"""

from patchsorter.db.head_client.database_manager import DatabaseManager
from patchsorter.db.utils import SessionManager
from patchsorter.db.head_client import get_client as _get_head_client
from patchsorter.db import head_client


def get_database_manager() -> DatabaseManager:
    """Convenience: construct a DatabaseManager using the head client."""
    return DatabaseManager(_get_head_client())


__all__ = [
    "SessionManager",
    "DatabaseManager",
    "get_database_manager",
    "head_client",
]
