from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from patchsorter.db.head_client.patch import PatchStore
from patchsorter.db.head_client.confusion_matrix import ConfusionMatrixStore
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.config.constants import PredPatchSuffix


class ProjectStore:
    """Data-access methods for the ``project`` reference table.

    Args:
        session: An active SQLAlchemy Session provided by the application's
            session factory (SessionManager) — typically injected via FastAPI
            dependency injection.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    # ------------------------------------------------------------------ #
    # CRUD                                                                 #
    # ------------------------------------------------------------------ #

    def create(self, name: str, description: Optional[str] = None) -> Dict[str, Any]:
        """Insert a new project and return the created row.

        Args:
            name: Human-readable project name.  Must be unique across all
                projects.
            description: Optional longer description of the project.

        Returns:
            A dict with ``project_id``, ``project_name``, and ``description``.
        """
        row = self._session.execute(
            text(
                """
                INSERT INTO project (project_name, description)
                VALUES (:name, :description)
                RETURNING project_id, project_name, description
                """
            ),
            {"name": name, "description": description},
        ).mappings().one()
        result = dict(row)
        SettingsStore(self._session).seed_project_settings(result["project_id"])
        return result

    def list_all(self) -> List[Dict[str, Any]]:
        """Return all projects ordered by ``project_id`` ascending.

        Returns:
            A list of dicts, one per project.  Empty list if no projects
            exist.
        """
        rows = self._session.execute(
            text("SELECT * FROM project ORDER BY project_id")
        ).mappings().all()
        return [dict(r) for r in rows]

    def delete(self, project_id: int) -> None:
        """Delete a project and all its associated data.

        Follows the Project Deletion Protocol:

        1. ``DROP TABLE … CASCADE`` the four per-project distributed tables.
           Dropping with CASCADE removes all foreign-key constraints that
           reference these tables.
        2. Delete all ``label_class`` rows for this project.
        3. Delete all ``image`` rows for this project.
        4. Delete all ``settings`` rows for this project.
        5. Delete the ``project`` row.

        All five steps execute inside a single atomic transaction managed by
        the session.

        Args:
            project_id: The integer ID of the project to delete.

        Warning:
            This is a destructive and irreversible operation.
        """
        n = project_id
        cm_tables = ", ".join(
            ConfusionMatrixStore.build_table_name(n, lvl) for lvl in range(8, 13)
        )
        self._session.execute(
            text(
                f"""
                DROP TABLE IF EXISTS
                    {PatchStore.build_table_name(n)},
                    {PatchStore.build_pred_table_name(n, PredPatchSuffix.LATEST)},
                    {PatchStore.build_pred_table_name(n, PredPatchSuffix.LAST)},
                    {cm_tables}
                CASCADE;
                """
            )
        )
        self._session.execute(
            text("DELETE FROM label_class WHERE project_id = :project_id"),
            {"project_id": project_id},
        )
        self._session.execute(
            text("DELETE FROM image WHERE project_id = :project_id"),
            {"project_id": project_id},
        )
        self._session.execute(
            text("DELETE FROM settings WHERE project_id = :project_id"),
            {"project_id": project_id},
        )
        self._session.execute(
            text("DELETE FROM project WHERE project_id = :project_id"),
            {"project_id": project_id},
        )
