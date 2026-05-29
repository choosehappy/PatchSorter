"""Canonical table-name helpers for per-project distributed tables.

All project-scoped table names are constructed here so that models,
stores, and schema management share a single source of truth.
"""

from patchsorter.config.constants import PredPatchSuffix


def patch_table(project_id: int) -> str:
    return f"project{project_id}_patch"


def pred_patch_table(project_id: int, suffix: PredPatchSuffix) -> str:
    """Return the pred_patch table name for the given project and suffix.

    Args:
        project_id: Integer project ID.
        suffix: Either ``PredPatchSuffix.LATEST`` or ``PredPatchSuffix.LAST``.
    """
    return f"project{project_id}_pred_patch_{suffix.value}"


def confusion_matrix_table(project_id: int, level: int | None = None) -> str:
    if level is None:
        return f"project{project_id}_confusion_matrix_l"
    return f"project{project_id}_confusion_matrix_l{level}"
