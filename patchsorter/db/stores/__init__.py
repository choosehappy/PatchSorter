"""Per-table data-access stores for PatchSorter.

Each store class is responsible for a single table (or a closely related
pair of tables) and receives an injected SQLAlchemy :class:`~sqlalchemy.orm.Session`
at construction time.

Exports:

- :class:`ConfusionMatrixStore` — ``project{N}_confusion_matrix_l{level}``
- :class:`ImageStore` — ``image``
- :class:`LabelClassStore` — ``label_class``
- :class:`LogStore` — ``log``
- :class:`PatchStore` — ``project{N}_patch``
- :class:`PredPatchStore` — ``project{N}_pred_patch_latest`` / ``_last``
- :class:`ProjectStore` — ``project`` + per-project distributed tables
- :class:`SettingsStore` — ``settings``
"""

from patchsorter.db.stores.confusion_matrix import ConfusionMatrixStore
from patchsorter.db.stores.image import ImageStore
from patchsorter.db.stores.label_class import LabelClassStore
from patchsorter.db.stores.log import LogStore
from patchsorter.db.stores.patch import PatchStore
from patchsorter.db.stores.pred_patch import PredPatchStore
from patchsorter.db.stores.project import ProjectStore
from patchsorter.db.stores.settings import SettingsStore

__all__ = [
    "ConfusionMatrixStore",
    "ImageStore",
    "LabelClassStore",
    "LogStore",
    "PatchStore",
    "PredPatchStore",
    "ProjectStore",
    "SettingsStore",
]
