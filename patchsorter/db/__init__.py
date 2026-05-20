"""Database layer for PatchSorter.

Clients own the session factory and expose :meth:`get_session` as a context
manager.  Pass the yielded session into store constructors to run operations:

.. code-block:: python

    from patchsorter.db.db_client import get_client
    from patchsorter.db.stores.patch import PatchStore

    client = get_client()
    with client.get_session() as session:
        patches = PatchStore(project_id, session)
        rows = patches.fetch(limit=50)

Clients:

- :class:`~patchsorter.db.db_client.CitusHeadClient` — Citus coordinator node.
- :class:`~patchsorter.db.db_client.CitusWorkerClient` — Citus worker node.

FastAPI dependency providers:

- :func:`~patchsorter.db.db_client.get_client`
- :func:`~patchsorter.db.db_client.get_worker_client`
"""

from patchsorter.db import stores
from patchsorter.db.db_client import (
    CitusHeadClient,
    CitusWorkerClient,
    get_client,
    get_worker_client,
)

__all__ = [
    "stores",
    "CitusHeadClient",
    "CitusWorkerClient",
    "get_client",
    "get_worker_client",
]
