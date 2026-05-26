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

from patchsorter.db.constants import (
    CITUS_HEAD_HOST,
    CITUS_HEAD_PORT,
    CITUS_HEAD_DB,
    CITUS_HEAD_USER,
    CITUS_HEAD_PASSWORD,
)
from patchsorter.db.utils import SessionManager
from patchsorter.db.head_client.confusion_matrix import ConfusionMatrixStore
from patchsorter.db.head_client.image import ImageStore
from patchsorter.db.head_client.label_class import LabelClassStore
from patchsorter.db.head_client.log import LogStore
from patchsorter.db.head_client.patch import PatchStore
from patchsorter.db.head_client.project import ProjectStore
from patchsorter.db.head_client.settings import SettingsStore

__all__ = [
    "ConfusionMatrixStore",
    "ImageStore",
    "LabelClassStore",
    "LogStore",
    "PatchStore",
    "ProjectStore",
    "SettingsStore",
    "get_client",
]


# Convenience factory to obtain a SessionManager configured for the head (coordinator)
def get_client() -> SessionManager:
    """Return a `SessionManager` configured for the head node using repo constants."""
    return SessionManager(
        host=CITUS_HEAD_HOST,
        port=CITUS_HEAD_PORT,
        dbname=CITUS_HEAD_DB,
        user=CITUS_HEAD_USER,
        password=CITUS_HEAD_PASSWORD,
    )
