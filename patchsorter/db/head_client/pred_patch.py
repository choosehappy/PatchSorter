"""Deprecated: prediction methods have been merged into PatchStore.

Import :class:`~patchsorter.db.head_client.patch.PatchStore` instead.
"""
from __future__ import annotations

import warnings

from patchsorter.db.head_client.patch import PatchStore as _PatchStore
from sqlalchemy.orm import Session


class PredPatchStore(_PatchStore):
    """Deprecated alias for :class:`~patchsorter.db.head_client.patch.PatchStore`.

    Prediction methods (``upsert_predictions``, ``fetch_predictions``,
    ``delete_predictions``) are now part of ``PatchStore``.  This class will
    be removed in a future release.
    """

    def __init__(self, project_id: int, session: Session) -> None:
        warnings.warn(
            "PredPatchStore is deprecated; use PatchStore instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(project_id, session)
