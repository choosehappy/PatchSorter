"""Worker client helpers (thin wrappers returning SessionManager for worker nodes)."""
from patchsorter.db.constants import (
    CITUS_WORKER_HOST,
    CITUS_WORKER_PORT,
    CITUS_WORKER_DB,
    CITUS_WORKER_USER,
    CITUS_WORKER_PASSWORD,
)
from patchsorter.db.utils import SessionManager
from patchsorter.db.worker_client.patch import WorkerPatchStore

__all__ = ["get_client", "WorkerPatchStore"]


def get_client() -> SessionManager:
    """Return a `SessionManager` configured for a worker node using repo constants."""
    return SessionManager(
        host=CITUS_WORKER_HOST,
        port=CITUS_WORKER_PORT,
        dbname=CITUS_WORKER_DB,
        user=CITUS_WORKER_USER,
        password=CITUS_WORKER_PASSWORD,
    )
