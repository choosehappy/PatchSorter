"""Per-table data-access stores for PatchSorter.

Each store class is responsible for a single table (or a closely related
pair of tables) and receives an injected SQLAlchemy :class:`~sqlalchemy.orm.Session`
at construction time.

Exports:

- :class:`ConfusionMatrixStore` — ``project{N}_confusion_matrix_l{level}``
- :class:`ImageStore` — ``image``
- :class:`LabelClassStore` — ``label_class``
- :class:`LogStore` — ``log``
- :class:`PatchStore` — ``project{N}_patch`` / ``project{N}_pred_patch_latest`` / ``_last``
- :class:`ProjectStore` — ``project`` + per-project distributed tables
- :class:`SettingsStore` — ``settings``
"""

import os
from patchsorter.db.utils import SessionManager
from patchsorter.db.head_client.confusion_matrix import ConfusionMatrixStore
from patchsorter.db.head_client.image import ImageStore
from patchsorter.db.head_client.label_class import LabelClassStore
from patchsorter.db.head_client.log import LogStore
from patchsorter.db.head_client.models import (
    Base, Image, LabelClass, Log, Project, Setting,
    all_project_models, confusion_matrix_model, patch_model, pred_patch_model,
)
from patchsorter.db.head_client.patch import PatchStore
from patchsorter.db.head_client.project import ProjectStore
from patchsorter.db.head_client.settings import SettingsStore

__all__ = [
    "Base",
    "ConfusionMatrixStore",
    "Image",
    "ImageStore",
    "LabelClass",
    "LabelClassStore",
    "Log",
    "LogStore",
    "PatchStore",
    "Project",
    "ProjectStore",
    "Setting",
    "SettingsStore",
    "all_project_models",
    "confusion_matrix_model",
    "get_client",
    "patch_model",
    "pred_patch_model",
]


# Module-level cache to avoid creating a new engine per request
_head_client: SessionManager | None = None


def get_client(is_local: bool = True) -> SessionManager:
    """Return a `SessionManager` configured for the head node using repo constants."""
    global _head_client
    if _head_client is None:
        _head_client = SessionManager(
            host=os.environ.get("CITUS_LOCAL_HOST" if is_local else "CITUS_HEAD_HOST", "localhost"),
            port=int(os.environ.get("CITUS_LOCAL_PORT" if is_local else "CITUS_HEAD_PORT", "5439")),
            dbname=os.environ.get("CITUS_LOCAL_DB" if is_local else "CITUS_HEAD_DB", "postgres"),
            user=os.environ.get("CITUS_LOCAL_USER" if is_local else "CITUS_HEAD_USER", "postgres"),
            password=os.environ.get("CITUS_LOCAL_PASSWORD" if is_local else "CITUS_HEAD_PASSWORD", "password"),
        )
    return _head_client
