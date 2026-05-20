"""Unit of Work implementations for the Citus coordinator and worker nodes.

Provides two context-manager classes that encapsulate a SQLAlchemy session
and expose per-table stores as attributes:

- :class:`CitusHeadUnitOfWork` — for the Citus coordinator node.  Exposes all
  reference-table stores plus the per-project distributed stores.
- :class:`CitusWorkerUnitOfWork` — for direct shard-level access on a Citus
  worker node.  Exposes only per-project distributed stores; reference tables
  should be mutated through the coordinator.

FastAPI dependency providers and ``Annotated`` type aliases are included for
convenient injection into route handlers.

Example usage in a FastAPI route::

    from patchsorter.db.unit_of_work import ProjectUOW

    @router.get("/projects/{project_id}/patches")
    async def list_patches(project_id: int, uow: ProjectUOW):
        return uow.patches.fetch(limit=50)
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Annotated, Generator, Optional

from fastapi import Depends
from sqlalchemy.orm import Session

from patchsorter.db.db_client import CitusHeadClient, CitusWorkerClient
from patchsorter.db.stores.confusion_matrix import ConfusionMatrixStore
from patchsorter.db.stores.image import ImageStore
from patchsorter.db.stores.label_class import LabelClassStore
from patchsorter.db.stores.log import LogStore
from patchsorter.db.stores.patch import PatchStore
from patchsorter.db.stores.pred_patch import PredPatchStore
from patchsorter.db.stores.project import ProjectStore
from patchsorter.db.stores.settings import SettingsStore

_DEFAULT_CM_LEVEL = 12


# --------------------------------------------------------------------------- #
# Head-node Unit of Work                                                       #
# --------------------------------------------------------------------------- #

class CitusHeadUnitOfWork:
    """Unit of Work for the Citus coordinator node.

    Manages a single SQLAlchemy session and instantiates all data stores
    scoped to that session.  On ``__exit__`` the session is committed if no
    exception occurred, or rolled back otherwise.

    Reference-table stores (``projects``, ``images``, ``label_classes``,
    ``settings``, ``logs``) are always available after entering the context.
    Per-project distributed stores (``patches``, ``pred_patches``,
    ``confusion_matrix``) are available when *project_id* is provided.

    DDL operations that cannot run inside a regular session transaction
    (e.g. ``ALTER TABLE``, ``DROP TABLE``) should use the
    :meth:`raw_connection` context manager.

    Args:
        client: A :class:`~patchsorter.db.db_client.CitusHeadClient` that
            provides the engine and session factory.
        project_id: Optional integer project ID.  When supplied, the
            per-project stores (``patches``, ``pred_patches``,
            ``confusion_matrix``) are initialised automatically.
        cm_level: Confusion-matrix hierarchical grid level to expose through
            the ``confusion_matrix`` store.  Must be 8–12.  Defaults to
            ``12`` (finest resolution).

    Example::

        with CitusHeadUnitOfWork(client, project_id=1) as uow:
            project = uow.projects.get_by_uid(uid)
            patches = uow.patches.fetch(limit=100)
    """

    projects: ProjectStore
    images: ImageStore
    label_classes: LabelClassStore
    settings: SettingsStore
    logs: LogStore
    patches: PatchStore
    pred_patches: PredPatchStore
    confusion_matrix: ConfusionMatrixStore

    def __init__(
        self,
        client: CitusHeadClient,
        project_id: Optional[int] = None,
        cm_level: int = _DEFAULT_CM_LEVEL,
    ) -> None:
        self._client = client
        self._project_id = project_id
        self._cm_level = cm_level
        self._session: Optional[Session] = None

    def __enter__(self) -> CitusHeadUnitOfWork:
        self._session = self._client.session_factory()
        self.projects = ProjectStore(self._session)
        self.images = ImageStore(self._session)
        self.label_classes = LabelClassStore(self._session)
        self.settings = SettingsStore(self._session)
        self.logs = LogStore(self._session)
        if self._project_id is not None:
            self.patches = PatchStore(self._project_id, self._session)
            self.pred_patches = PredPatchStore(self._project_id, self._session)
            self.confusion_matrix = ConfusionMatrixStore(
                self._project_id, self._cm_level, self._session
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._session is None:
            return
        if exc_type:
            self._session.rollback()
        else:
            self._session.commit()
        self._session.close()
        self._session = None

    @contextmanager
    def raw_connection(self):
        """Context manager providing a raw psycopg connection for DDL operations.

        Commits on clean exit and rolls back on exception.  The connection is
        returned to the pool after the context exits.

        Yields:
            A raw psycopg connection from the engine pool.

        Example::

            with uow.raw_connection() as conn:
                uow.projects.create_project_tables(project_id, conn)
        """
        conn = self._client.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# Worker-node Unit of Work                                                     #
# --------------------------------------------------------------------------- #

class CitusWorkerUnitOfWork:
    """Unit of Work for direct shard-level access on a Citus worker node.

    Exposes only the per-project distributed stores because reference tables
    (``project``, ``image``, ``label_class``, ``settings``, ``log``) are
    replicated read-only copies on workers and should be mutated exclusively
    through the coordinator.

    Useful for performance-sensitive reads that benefit from bypassing the
    coordinator routing layer, or for shard-local batch operations.

    Args:
        client: A :class:`~patchsorter.db.db_client.CitusWorkerClient` that
            connects directly to a worker node.
        project_id: Integer project ID whose shard tables to access.
        cm_level: Confusion-matrix hierarchical grid level.  Defaults to
            ``12``.

    Example::

        with CitusWorkerUnitOfWork(worker_client, project_id=1) as uow:
            raw_patches = uow.patches.fetch_by_shards([102008, 102009])
    """

    patches: PatchStore
    pred_patches: PredPatchStore
    confusion_matrix: ConfusionMatrixStore

    def __init__(
        self,
        client: CitusWorkerClient,
        project_id: int,
        cm_level: int = _DEFAULT_CM_LEVEL,
    ) -> None:
        self._client = client
        self._project_id = project_id
        self._cm_level = cm_level
        self._session: Optional[Session] = None

    def __enter__(self) -> CitusWorkerUnitOfWork:
        self._session = self._client.session_factory()
        self.patches = PatchStore(self._project_id, self._session)
        self.pred_patches = PredPatchStore(self._project_id, self._session)
        self.confusion_matrix = ConfusionMatrixStore(
            self._project_id, self._cm_level, self._session
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._session is None:
            return
        if exc_type:
            self._session.rollback()
        else:
            self._session.commit()
        self._session.close()
        self._session = None

    @contextmanager
    def raw_connection(self):
        """Context manager providing a raw psycopg connection for DDL operations.

        Commits on clean exit and rolls back on exception.

        Yields:
            A raw psycopg connection from the worker engine pool.
        """
        conn = self._client.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# Singleton clients (override at application startup if needed)               #
# --------------------------------------------------------------------------- #

_head_client: Optional[CitusHeadClient] = None
_worker_client: Optional[CitusWorkerClient] = None


def get_client() -> CitusHeadClient:
    """Return the application-global :class:`~patchsorter.db.db_client.CitusHeadClient`.

    The client is created on first call using environment-variable defaults.
    Override ``_head_client`` before the first request to supply a custom
    instance (e.g. in tests).

    Returns:
        The shared :class:`~patchsorter.db.db_client.CitusHeadClient`.
    """
    global _head_client
    if _head_client is None:
        _head_client = CitusHeadClient()
    return _head_client


def get_worker_client() -> CitusWorkerClient:
    """Return the application-global :class:`~patchsorter.db.db_client.CitusWorkerClient`.

    Returns:
        The shared :class:`~patchsorter.db.db_client.CitusWorkerClient`.
    """
    global _worker_client
    if _worker_client is None:
        _worker_client = CitusWorkerClient()
    return _worker_client


# --------------------------------------------------------------------------- #
# FastAPI dependency providers                                                 #
# --------------------------------------------------------------------------- #

def get_head_uow(
    client: CitusHeadClient = Depends(get_client),
) -> Generator[CitusHeadUnitOfWork, None, None]:
    """FastAPI dependency that yields a coordinator UoW without a project scope.

    Suitable for routes that operate on reference tables only (listing
    projects, creating images, etc.) and do not need per-project distributed
    stores.

    Args:
        client: Injected :class:`~patchsorter.db.db_client.CitusHeadClient`.

    Yields:
        An active :class:`CitusHeadUnitOfWork` (already entered).
    """
    with CitusHeadUnitOfWork(client) as uow:
        yield uow


def get_project_uow(
    project_id: int,
    client: CitusHeadClient = Depends(get_client),
) -> Generator[CitusHeadUnitOfWork, None, None]:
    """FastAPI dependency that yields a project-scoped coordinator UoW.

    When used in a route with a ``{project_id}`` path parameter, FastAPI
    automatically injects ``project_id`` from the URL.  All per-project
    distributed stores (``patches``, ``pred_patches``, ``confusion_matrix``)
    are available on the yielded UoW.

    Args:
        project_id: Injected from the route path parameter.
        client: Injected :class:`~patchsorter.db.db_client.CitusHeadClient`.

    Yields:
        An active :class:`CitusHeadUnitOfWork` (already entered) with
        per-project stores initialised.
    """
    with CitusHeadUnitOfWork(client, project_id=project_id) as uow:
        yield uow


def get_worker_uow(
    project_id: int,
    client: CitusWorkerClient = Depends(get_worker_client),
) -> Generator[CitusWorkerUnitOfWork, None, None]:
    """FastAPI dependency that yields a worker-node UoW for a project.

    Args:
        project_id: Injected from the route path parameter.
        client: Injected :class:`~patchsorter.db.db_client.CitusWorkerClient`.

    Yields:
        An active :class:`CitusWorkerUnitOfWork` (already entered).
    """
    with CitusWorkerUnitOfWork(client, project_id=project_id) as uow:
        yield uow


# --------------------------------------------------------------------------- #
# Annotated type aliases for FastAPI injection                                 #
# --------------------------------------------------------------------------- #

HeadUOW = Annotated[CitusHeadUnitOfWork, Depends(get_head_uow)]
"""Type alias for injecting a coordinator UoW without project scope.

Use in route signatures::

    @router.get("/projects")
    async def list_projects(uow: HeadUOW):
        return uow.projects.list_all()
"""

ProjectUOW = Annotated[CitusHeadUnitOfWork, Depends(get_project_uow)]
"""Type alias for injecting a project-scoped coordinator UoW.

Requires a ``{project_id}`` path parameter in the route::

    @router.get("/projects/{project_id}/patches")
    async def list_patches(project_id: int, uow: ProjectUOW):
        return uow.patches.fetch(limit=100)
"""

WorkerUOW = Annotated[CitusWorkerUnitOfWork, Depends(get_worker_uow)]
"""Type alias for injecting a project-scoped worker-node UoW.

Requires a ``{project_id}`` path parameter::

    @router.get("/worker/projects/{project_id}/shards")
    async def read_shard(project_id: int, uow: WorkerUOW):
        return uow.patches.fetch_by_shards([102008])
"""
