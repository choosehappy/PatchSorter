from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from patchsorter.db.head_client.models import Base, all_project_models
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

    # ------------------------------------------------------------------ #
    # Per-project DDL                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def create_project_tables(project_id: int, engine) -> None:
        """Create and distribute the per-project tables for *project_id*.

        Creates (idempotent — ``checkfirst=True``):

        - ``project{N}_patch`` — distributed by ``patch_id``.
        - ``project{N}_pred_patch_latest`` — co-located with patch.
        - ``project{N}_pred_patch_last`` — co-located with patch.
        - ``project{N}_confusion_matrix_l8`` … ``project{N}_confusion_matrix_l12``
          — each distributed by ``shard_id``, co-located with patch.

        A partial index on ``count <= 0`` is created for each confusion-matrix
        level to accelerate the trigger cleanup pass.

        Args:
            project_id: The integer project ID.  Used as the ``{N}`` suffix in
                all table names.
            engine: A SQLAlchemy ``Engine`` for the target database.  DDL is
                emitted via ``Base.metadata.create_all``; Citus distribution
                statements run on a raw autocommit connection obtained from the
                same engine.
        """
        n = project_id
        models = all_project_models(n)
        tables = [m.__table__ for m in models]
        Base.metadata.create_all(engine, tables=tables, checkfirst=True)

        patch_tbl = PatchStore.build_table_name(n)
        distribution = [
            f"SELECT create_distributed_table('{patch_tbl}', 'patch_id');",
            f"SELECT create_distributed_table('{PatchStore.build_pred_table_name(n, PredPatchSuffix.LATEST)}', 'patch_id', colocate_with => '{patch_tbl}');",
            f"SELECT create_distributed_table('{PatchStore.build_pred_table_name(n, PredPatchSuffix.LAST)}', 'patch_id', colocate_with => '{patch_tbl}');",
            *[
                f"SELECT create_distributed_table('{ConfusionMatrixStore.build_table_name(n, lvl)}', 'shard_id', colocate_with => '{patch_tbl}');"
                for lvl in range(8, 13)
            ],
        ]
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            for stmt in distribution:
                try:
                    conn.exec_driver_sql(stmt)
                except Exception as exc:
                    print(f"Distribution command failed (may already be distributed): {exc}")

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
