from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from patchsorter.api.v1.label_class.models import LabelClassResponse
from patchsorter.config.constants import UNASSIGNED_CLASS_ID, ANNOTATION_CLASS_COLOR_PALETTES
from patchsorter.db.head_client.models import LabelClass, build_table_name, build_pred_table_name
from patchsorter.db.head_client.confusion_matrix import ConfusionMatrixStore

from patchsorter.config.constants import PredPatchSuffix




class ColorPalette:
    """Yield unused colors from the configured palette for a given project."""

    def __init__(self, project_id: int) -> None:
        self._color_list = ANNOTATION_CLASS_COLOR_PALETTES['default']
        self._project_id = project_id

    def get_unused_color(self, existing: List[LabelClassResponse]) -> str:
        """Return the first palette color not already used by *existing* label classes."""
        used_colors = {lc.color_code for lc in existing if lc.color_code is not None}
        for color in self._color_list:
            if color not in used_colors:
                return color
        # Exhausted the palette — fall back to the first entry
        return self._color_list[0]


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

        The current timestamp is assigned automatically.  ``label_class_id``
        is assigned by the ``label_class_assign_id`` database trigger (per
        project, starting at 0), so it is not computed here.

        Args:
            project_id: Foreign key to the owning project.
            name: Display name for the class.  Must be unique among the
                project's active (non-deleted) classes.
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

    def update(
        self,
        label_class_id: int,
        project_id: int,
        name: Optional[str] = None,
        color_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update a label class and return the updated row.

        Args:
            label_class_id: The integer ID of the label class to update.
            project_id: The integer ID of the owning project.
            name: Optional new display name.
            color_code: Optional new CSS colour string.

        Returns:
            A dict with all columns of the updated label-class row.

        Raises:
            RuntimeError: If the label class is not found.
        """
        row = (
            self._session.query(LabelClass)
            .filter(
                LabelClass.label_class_id == label_class_id,
                LabelClass.project_id == project_id,
                LabelClass.is_deleted.is_(False),
            )
            .first()
        )
        if row is None:
            raise RuntimeError(
                f"Label class {label_class_id} not found in project {project_id}"
            )
        if name is not None:
            row.name = name
        if color_code is not None:
            row.color_code = color_code
        return {c.name: getattr(row, c.name) for c in row.__table__.columns}

    def list_by_project(
        self, project_id: int, include_deleted: bool = False
    ) -> List[LabelClassResponse]:
        """Return the label classes for a project ordered by ``label_class_id``.

        Args:
            project_id: The integer ID of the project.
            include_deleted: Include soft-deleted classes.  Required when
                sizing the model output, since deleted classes keep their slot.

        Returns:
            A list of LabelClassResponse Pydantic models.
        """
        query = self._session.query(LabelClass).filter(LabelClass.project_id == project_id)
        if not include_deleted:
            query = query.filter(LabelClass.is_deleted.is_(False))
        rows = query.order_by(LabelClass.label_class_id).all()
        return [LabelClassResponse.model_validate(row) for row in rows]

    def delete(self, label_class_id: int, project_id: int) -> None:
        """Soft-delete a label class following the Annotation Class Deletion Protocol.

        The "Unlabeled" class (``label_class_id = UNASSIGNED_CLASS_ID``) is reserved and cannot
        be deleted.

        Deletion steps (all within the current session's transaction):

        1. Reset ``label_class_id`` on all patches in the project's patch table
           that reference the deleted class back to ``UNASSIGNED_CLASS_ID`` (Unlabeled).
        2. Reset ``label_class_id`` on all rows in ``project{N}_pred_patch_latest``
           that reference the deleted class back to ``UNASSIGNED_CLASS_ID``.
        3. Perform the same reset on ``project{N}_pred_patch_last``.
        4. Reset ``pred_label`` and ``gt_label`` in all five confusion-matrix
           tables that reference the deleted class back to ``UNASSIGNED_CLASS_ID``.
        5. Set ``is_deleted = TRUE`` on the ``label_class`` row.

        Steps 1–4 must complete before step 5.

        The row is kept, so the ID is never reused and the model output slot
        stays stable.

        Args:
            label_class_id: The integer ID of the label class to delete.
            project_id: The integer ID of the owning project.  Used to
                resolve project-scoped table names.

        Raises:
            ValueError: If *label_class_id* is ``UNASSIGNED_CLASS_ID`` (the reserved Unlabeled
                class).
            RuntimeError: If the label class does not exist or is already deleted.
        """
        if label_class_id == UNASSIGNED_CLASS_ID:
            raise ValueError(
                f"The 'Unlabeled' label class (id={UNASSIGNED_CLASS_ID}) is reserved and cannot be deleted."
            )

        exists = self._session.execute(
            text(
                "SELECT 1 FROM label_class WHERE label_class_id = :lcid "
                "AND project_id = :pid AND NOT is_deleted"
            ),
            {"lcid": label_class_id, "pid": project_id},
        ).first()
        if exists is None:
            raise RuntimeError(
                f"Label class {label_class_id} not found in project {project_id}"
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

        # Step 5: soft-delete the label class row.
        self._session.execute(
            text(
                "UPDATE label_class SET is_deleted = TRUE "
                "WHERE label_class_id = :lcid AND project_id = :pid"
            ),
            {"lcid": label_class_id, "pid": project_id},
        )
