from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

_UNLABELED_CLASS_ID = 1
"""Reserved ``label_class_id`` for the "Unlabeled" class.  Cannot be deleted."""


class LabelClassStore:
    """Data-access methods for the ``label_class`` reference table.

    Args:
        session: An active SQLAlchemy session provided by
            :class:`~patchsorter.db.unit_of_work.CitusHeadUnitOfWork`.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        project_id: int,
        name: str,
        color_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert a new label class and return the created row.

        A UUID and the current timestamp are assigned automatically.

        Args:
            project_id: Foreign key to the owning project.
            name: Display name for the class.  Must be unique within the
                project.
            color_code: Optional CSS colour string (e.g. ``"#FF5733"``).

        Returns:
            A dict with all columns of the newly created label-class row.
        """
        row = self._session.execute(
            text(
                """
                INSERT INTO label_class (project_id, name, color_code, event_ts)
                VALUES (:project_id, :name, :color_code, NOW())
                RETURNING *
                """
            ),
            {"project_id": project_id, "name": name, "color_code": color_code},
        ).mappings().one()
        return dict(row)

    def get_by_uid(self, label_class_uid: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Fetch a label class by its external UUID.

        Args:
            label_class_uid: The external UUID of the label class.

        Returns:
            A dict with all label-class columns, or ``None`` if not found.
        """
        row = self._session.execute(
            text("SELECT * FROM label_class WHERE label_class_uid = :uid"),
            {"uid": str(label_class_uid)},
        ).mappings().one_or_none()
        return dict(row) if row else None

    def list_by_project(self, project_id: int) -> List[Dict[str, Any]]:
        """Return all label classes for a project ordered by ``label_class_id``.

        Args:
            project_id: The integer ID of the project.

        Returns:
            A list of dicts, one per label class.
        """
        rows = self._session.execute(
            text(
                "SELECT * FROM label_class WHERE project_id = :pid ORDER BY label_class_id"
            ),
            {"pid": project_id},
        ).mappings().all()
        return [dict(r) for r in rows]

    def delete(self, label_class_id: int, project_id: int) -> None:
        """Delete a label class following the Annotation Class Deletion Protocol.

        The "Unlabeled" class (``label_class_id = 1``) is reserved and cannot
        be deleted.

        Deletion steps (all within the current session's transaction):

        1. Reset ``label_class_id`` on all patches in the project's patch table
           that reference the deleted class back to ``1`` (Unlabeled).
        2. Reset ``label_class_id`` on all rows in ``project{N}_pred_patch_latest``
           that reference the deleted class back to ``1``.
        3. Perform the same reset on ``project{N}_pred_patch_last``.
        4. Reset ``pred_label`` and ``gt_label`` in all five confusion-matrix
           tables that reference the deleted class back to ``1``.
        5. Delete the ``label_class`` row.

        Steps 1–4 must complete before step 5.

        Args:
            label_class_id: The integer ID of the label class to delete.
            project_id: The integer ID of the owning project.  Used to
                resolve project-scoped table names.

        Raises:
            ValueError: If *label_class_id* is ``1`` (the reserved Unlabeled
                class).
        """
        if label_class_id == _UNLABELED_CLASS_ID:
            raise ValueError(
                "The 'Unlabeled' label class (id=1) is reserved and cannot be deleted."
            )

        n = project_id

        # Step 1: reset patch ground-truth labels.
        self._session.execute(
            text(
                f"UPDATE project{n}_patch SET label_class_id = 1 WHERE label_class_id = :lcid"
            ),
            {"lcid": label_class_id},
        )

        # Steps 2 & 3: reset prediction labels.
        for pred_table in (
            f"project{n}_pred_patch_latest",
            f"project{n}_pred_patch_last",
        ):
            self._session.execute(
                text(
                    f"UPDATE {pred_table} SET label_class_id = 1 WHERE label_class_id = :lcid"
                ),
                {"lcid": label_class_id},
            )

        # Step 4: reset confusion-matrix pred_label / gt_label references.
        for lvl in range(8, 13):
            cm_table = f"project{n}_confusion_matrix_l{lvl}"
            self._session.execute(
                text(
                    f"UPDATE {cm_table} SET pred_label = 1 WHERE pred_label = :lcid"
                ),
                {"lcid": label_class_id},
            )
            self._session.execute(
                text(
                    f"UPDATE {cm_table} SET gt_label = 1 WHERE gt_label = :lcid"
                ),
                {"lcid": label_class_id},
            )

        # Step 5: delete the label class row.
        self._session.execute(
            text("DELETE FROM label_class WHERE label_class_id = :lcid"),
            {"lcid": label_class_id},
        )
