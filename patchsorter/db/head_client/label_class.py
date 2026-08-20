from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from patchsorter.api.v1.label_class.models import LabelClassResponse
from patchsorter.config.constants import UNASSIGNED_CLASS_ID
from patchsorter.db.head_client.models import LabelClass, build_table_name, build_pred_table_name
from patchsorter.db.head_client.confusion_matrix import ConfusionMatrixStore

from patchsorter.config.constants import PredPatchSuffix




class LabelClassStore:
    """Data-access methods for the ``label_class`` reference table.

    Args:
        session: An active SQLAlchemy Session provided by the application's
            session factory (SessionManager) — typically injected via FastAPI
            dependency injection.
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

        The current timestamp is assigned automatically.

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
                INSERT INTO label_class (project_id, name, color_code)
                VALUES (:project_id, :name, :color_code)
                RETURNING *
                """
            ),
            {"project_id": project_id, "name": name, "color_code": color_code},
        ).mappings().one()
        return dict(row)

    def list_by_project(self, project_id: int) -> List[LabelClassResponse]:
        """Return all label classes for a project ordered by ``label_class_id``.

        Args:
            project_id: The integer ID of the project.

        Returns:
            A list of LabelClassResponse Pydantic models.
        """
        project_filter = or_(LabelClass.project_id == project_id, LabelClass.project_id.is_(None))

        rows = (
            self._session.query(LabelClass)
            .filter(project_filter)
            .order_by(LabelClass.label_class_id)
            .all()
        )
        return [LabelClassResponse.model_validate(row) for row in rows]

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
        if label_class_id == UNASSIGNED_CLASS_ID:
            raise ValueError(
                f"The 'Unlabeled' label class (id={UNASSIGNED_CLASS_ID}) is reserved and cannot be deleted."
            )

        n = project_id

        # Step 1: reset patch ground-truth labels.
        self._session.execute(
            text(
                f"UPDATE {build_table_name(n)} SET label_class_id = {UNASSIGNED_CLASS_ID} WHERE label_class_id = :lcid"
            ),
            {"lcid": label_class_id},
        )

        # Steps 2 & 3: reset prediction labels.
        for tbl in (build_pred_table_name(n, PredPatchSuffix.LATEST), build_pred_table_name(n, PredPatchSuffix.LAST)):
            self._session.execute(
                text(
                    f"UPDATE {tbl} SET label_class_id = {UNASSIGNED_CLASS_ID} WHERE label_class_id = :lcid"
                ),
                {"lcid": label_class_id},
            )

        # Step 4: reset confusion-matrix pred_label / gt_label references.
        for lvl in range(8, 13):
            cm_tbl = ConfusionMatrixStore.build_table_name(n, lvl)
            self._session.execute(
                text(
                    f"UPDATE {cm_tbl} SET pred_label = {UNASSIGNED_CLASS_ID} WHERE pred_label = :lcid"
                ),
                {"lcid": label_class_id},
            )
            self._session.execute(
                text(
                    f"UPDATE {cm_tbl} SET gt_label = {UNASSIGNED_CLASS_ID} WHERE gt_label = :lcid"
                ),
                {"lcid": label_class_id},
            )

        # Step 5: delete the label class row.
        self._session.execute(
            text("DELETE FROM label_class WHERE label_class_id = :lcid"),
            {"lcid": label_class_id},
        )
