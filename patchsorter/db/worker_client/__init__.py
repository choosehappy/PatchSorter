"""Worker client helpers (thin wrappers returning SessionManager for worker nodes)."""
from patchsorter.db.constants import (
    CITUS_LOCAL_HOST,
    CITUS_LOCAL_PORT,
    CITUS_LOCAL_DB,
    CITUS_LOCAL_USER,
    CITUS_LOCAL_PASSWORD,
)
from patchsorter.db.utils import SessionManager
from patchsorter.db.worker_client.patch import WorkerPatchStore

__all__ = ["get_client", "WorkerPatchStore"]


# Module-level cache to avoid creating a new engine per request
_worker_client: SessionManager | None = None


def get_client() -> SessionManager:
    """Return a `SessionManager` configured for a worker node using repo constants."""
    global _worker_client
    if _worker_client is None:
        _worker_client = SessionManager(
            host=CITUS_LOCAL_HOST,
            port=CITUS_LOCAL_PORT,
            dbname=CITUS_LOCAL_DB,
            user=CITUS_LOCAL_USER,
            password=CITUS_LOCAL_PASSWORD,
        )
    return _worker_client
