"""Canonical table-name helpers for per-project distributed tables.

All project-scoped table names are constructed here so that models,
stores, and schema management share a single source of truth.
"""


def patch_table(project_id: int) -> str:
    return f"project{project_id}_patch"


def pred_patch_table(project_id: int, suffix: str) -> str:
    """Return the pred_patch table name for the given project and suffix.

    Args:
        project_id: Integer project ID.
        suffix: Either ``'latest'`` or ``'last'``.
    """
    return f"project{project_id}_pred_patch_{suffix}"


def confusion_matrix_table(project_id: int, level: int) -> str:
    return f"project{project_id}_confusion_matrix_l{level}"
