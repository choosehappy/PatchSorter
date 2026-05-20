"""Database layer for PatchSorter.

Exports the connection clients, Unit of Work classes, FastAPI dependency
providers, and the ``stores`` sub-package.

Clients:

- :class:`~patchsorter.db.db_client.CitusHeadClient` — Citus coordinator node.
- :class:`~patchsorter.db.db_client.CitusWorkerClient` — Citus worker node.

Unit of Work:

- :class:`~patchsorter.db.unit_of_work.CitusHeadUnitOfWork` — coordinator UoW.
- :class:`~patchsorter.db.unit_of_work.CitusWorkerUnitOfWork` — worker UoW.

FastAPI type aliases:

- :data:`~patchsorter.db.unit_of_work.HeadUOW`
- :data:`~patchsorter.db.unit_of_work.ProjectUOW`
- :data:`~patchsorter.db.unit_of_work.WorkerUOW`

FastAPI dependency providers:

- :func:`~patchsorter.db.unit_of_work.get_client`
- :func:`~patchsorter.db.unit_of_work.get_head_uow`
- :func:`~patchsorter.db.unit_of_work.get_project_uow`
- :func:`~patchsorter.db.unit_of_work.get_worker_client`
- :func:`~patchsorter.db.unit_of_work.get_worker_uow`
"""

from patchsorter.db import stores
from patchsorter.db.db_client import CitusHeadClient, CitusWorkerClient
from patchsorter.db.unit_of_work import (
    CitusHeadUnitOfWork,
    CitusWorkerUnitOfWork,
    HeadUOW,
    ProjectUOW,
    WorkerUOW,
    get_client,
    get_head_uow,
    get_project_uow,
    get_worker_client,
    get_worker_uow,
)

__all__ = [
    "stores",
    "CitusHeadClient",
    "CitusWorkerClient",
    "CitusHeadUnitOfWork",
    "CitusWorkerUnitOfWork",
    "HeadUOW",
    "ProjectUOW",
    "WorkerUOW",
    "get_client",
    "get_head_uow",
    "get_project_uow",
    "get_worker_client",
    "get_worker_uow",
]
