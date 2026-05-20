from __future__ import annotations

from sqlalchemy.orm import Session


class PredPatchStore:
    """Data-access methods for a project's prediction tables.

    Manages ``project{N}_pred_patch_latest`` and ``project{N}_pred_patch_last``,
    which store the two most recent prediction epochs for the project.

    Args:
        project_id: Integer ID of the project.  Used to construct the
            project-scoped table names.
        session: An active SQLAlchemy session provided by
            :class:`~patchsorter.db.unit_of_work.CitusHeadUnitOfWork` or
            :class:`~patchsorter.db.unit_of_work.CitusWorkerUnitOfWork`.
    """

    def __init__(self, project_id: int, session: Session) -> None:
        self.project_id = project_id
        self._session = session
        self.table_name = f"project{project_id}_pred_patch_latest"
        self._last_table = f"project{project_id}_pred_patch_last"

    def rotate_tables(self, raw_conn) -> None:
        """Rotate ``pred_patch_latest`` → ``pred_patch_last`` via a 3-way rename.

        No rows are copied and no tables are created or dropped.  Triggers
        travel with their physical shard objects and do not need to be
        re-registered after the rename.

        The rotation proceeds in four atomic steps:

        1. ``TRUNCATE project{N}_pred_patch_last`` — free stale data from the
           previous epoch.
        2. ``RENAME project{N}_pred_patch_last → project{N}_pred_patch_tmp``
        3. ``RENAME project{N}_pred_patch_latest → project{N}_pred_patch_last``
           — the current cycle's predictions become "last".
        4. ``RENAME project{N}_pred_patch_tmp → project{N}_pred_patch_latest``
           — the now-empty recycled shards become the new write target.

        All four statements execute inside a single atomic transaction on
        *raw_conn*.  ``ALTER TABLE … RENAME`` is DDL and cannot run inside a
        regular SQLAlchemy session transaction, hence the requirement for a
        raw connection.

        Args:
            raw_conn: A raw psycopg connection obtained from
                :meth:`~patchsorter.db.unit_of_work.CitusHeadUnitOfWork.raw_connection`.
                The caller's context manager commits on success.
        """
        n = self.project_id
        tmp_table = f"project{n}_pred_patch_tmp"
        with raw_conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {self._last_table};")
            cur.execute(
                f"ALTER TABLE {self._last_table} RENAME TO {tmp_table};"
            )
            cur.execute(
                f"ALTER TABLE {self.table_name} RENAME TO {self._last_table};"
            )
            cur.execute(
                f"ALTER TABLE {tmp_table} RENAME TO {self.table_name};"
            )
