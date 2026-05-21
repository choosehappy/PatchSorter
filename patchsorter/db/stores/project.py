from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class ProjectStore:
    """Data-access methods for the ``project`` reference table.

    Args:
        session: An active SQLAlchemy session provided by
            :meth:`~patchsorter.db.db_client.CitusHeadClient.get_session`.
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
        return dict(row)

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

    def create_project_tables(self, project_id: int, raw_conn) -> None:
        """Create and distribute the per-project tables for *project_id*.

        Creates (idempotent — ``IF NOT EXISTS``):

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
            raw_conn: A raw psycopg connection obtained from
                :meth:`~patchsorter.db.db_client.CitusHeadClient.get_connection`.
                The caller's context manager commits the connection on success.
        """
        n = project_id
        ddl = [
            f"""CREATE TABLE IF NOT EXISTS project{n}_patch (
                patch_id       BIGSERIAL PRIMARY KEY,
                patch_uid      INT,
                label_class_id SMALLINT  NOT NULL REFERENCES label_class(label_class_id),
                image_id       INT       NOT NULL REFERENCES image(image_id),
                working_mag    FLOAT     NOT NULL,
                patch_image    BYTEA     NOT NULL
            );""",
            f"""CREATE TABLE IF NOT EXISTS project{n}_pred_patch_latest (
                patch_id       BIGINT    PRIMARY KEY,
                embed_x        FLOAT     NOT NULL,
                embed_y        FLOAT     NOT NULL,
                grid_cell_i    SMALLINT  NOT NULL,
                grid_cell_j    SMALLINT  NOT NULL,
                event_ts       TIMESTAMP NOT NULL,
                label_class_id SMALLINT  NOT NULL REFERENCES label_class(label_class_id)
            );""",
            f"""CREATE TABLE IF NOT EXISTS project{n}_pred_patch_last (
                patch_id       BIGINT    PRIMARY KEY,
                embed_x        FLOAT     NOT NULL,
                embed_y        FLOAT     NOT NULL,
                grid_cell_i    SMALLINT  NOT NULL,
                grid_cell_j    SMALLINT  NOT NULL,
                event_ts       TIMESTAMP NOT NULL,
                label_class_id SMALLINT  NOT NULL REFERENCES label_class(label_class_id)
            );""",
            *[
                f"""CREATE TABLE IF NOT EXISTS project{n}_confusion_matrix_l{lvl} (
                    shard_id    BIGINT   NOT NULL,
                    grid_cell_i SMALLINT NOT NULL,
                    grid_cell_j SMALLINT NOT NULL,
                    bucket_date DATE     NOT NULL,
                    pred_label  SMALLINT NOT NULL REFERENCES label_class(label_class_id),
                    gt_label    SMALLINT NOT NULL REFERENCES label_class(label_class_id),
                    count       INT      NOT NULL,
                    PRIMARY KEY (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label)
                );"""
                for lvl in range(8, 13)
            ],
        ]
        distribution = [
            f"SELECT create_distributed_table('project{n}_patch', 'patch_id');",
            f"SELECT create_distributed_table('project{n}_pred_patch_latest', 'patch_id', colocate_with => 'project{n}_patch');",
            f"SELECT create_distributed_table('project{n}_pred_patch_last', 'patch_id', colocate_with => 'project{n}_patch');",
            *[
                f"SELECT create_distributed_table('project{n}_confusion_matrix_l{lvl}', 'shard_id', colocate_with => 'project{n}_patch');"
                for lvl in range(8, 13)
            ],
            *[
                f"CREATE INDEX IF NOT EXISTS idx_cm_p{n}_l{lvl}_nonpositive ON project{n}_confusion_matrix_l{lvl} (count) WHERE count <= 0;"
                for lvl in range(8, 13)
            ],
        ]
        with raw_conn.cursor() as cur:
            for stmt in ddl:
                cur.execute(stmt)
            for stmt in distribution:
                try:
                    cur.execute(stmt)
                except Exception as exc:
                    print(f"Distribution command failed (may already be distributed): {exc}")

    def delete(self, project_id: int, raw_conn) -> None:
        """Delete a project and all its associated data.

        Follows the Project Deletion Protocol:

        1. ``DROP TABLE … CASCADE`` the four per-project distributed tables.
           Dropping with CASCADE removes all foreign-key constraints that
           reference these tables.
        2. Delete all ``label_class`` rows for this project.
        3. Delete all ``image`` rows for this project.
        4. Delete all ``settings`` rows for this project.
        5. Delete the ``project`` row.

        All five steps execute inside a single atomic transaction on
        *raw_conn*.

        Args:
            project_id: The integer ID of the project to delete.
            raw_conn: A raw psycopg connection obtained from
                :meth:`~patchsorter.db.db_client.CitusHeadClient.get_connection`.

        Warning:
            This is a destructive and irreversible operation.
        """
        n = project_id
        cm_tables = ", ".join(
            f"project{n}_confusion_matrix_l{lvl}" for lvl in range(8, 13)
        )
        with raw_conn.cursor() as cur:
            cur.execute(
                f"""
                DROP TABLE IF EXISTS
                    project{n}_patch,
                    project{n}_pred_patch_latest,
                    project{n}_pred_patch_last,
                    {cm_tables}
                CASCADE;
                """
            )
            cur.execute(
                "DELETE FROM label_class WHERE project_id = %s;", (project_id,)
            )
            cur.execute(
                "DELETE FROM image WHERE project_id = %s;", (project_id,)
            )
            cur.execute(
                "DELETE FROM settings WHERE project_id = %s;", (project_id,)
            )
            cur.execute(
                "DELETE FROM project WHERE project_id = %s;", (project_id,)
            )
