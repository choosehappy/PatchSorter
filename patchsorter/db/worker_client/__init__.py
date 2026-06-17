"""Worker client helpers (thin wrappers returning SessionManager for worker nodes)."""
import os
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
            host=os.environ.get("CITUS_LOCAL_HOST", "localhost"),
            port=int(os.environ.get("CITUS_LOCAL_PORT", "5439")),
            dbname=os.environ.get("CITUS_LOCAL_DB", "postgres"),
            user=os.environ.get("CITUS_LOCAL_USER", "postgres"),
            password=os.environ.get("CITUS_LOCAL_PASSWORD", "password"),
        )
    return _worker_client
