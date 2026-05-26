from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class ImageStore:
    """Data-access methods for the ``image`` reference table.

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
        image_path: str,
        base_mag: float,
        base_width: int,
        base_height: int,
        deepzoom_tilesize: int,
        embedding_x: Optional[float] = None,
        embedding_y: Optional[float] = None,
        group_id: Optional[int] = None,
        train_test_split: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Insert a new image record and return the created row.

        Args:
            project_id: Foreign key to the owning project.
            name: Display name for the image.  Must be unique within the
                project.
            image_path: File path or URI of the whole-slide image on disk.
            base_mag: Base magnification level of the scanner (e.g. ``20.0``).
            base_width: Width of the image at base magnification in pixels.
            base_height: Height of the image at base magnification in pixels.
            deepzoom_tilesize: Tile size used for DeepZoom serving.
            embedding_x: Optional X coordinate of the image-level embedding.
            embedding_y: Optional Y coordinate of the image-level embedding.
            group_id: Optional group assignment from CohortFinder.
            train_test_split: Optional train/test split label from CohortFinder.

        Returns:
            A dict with all columns of the newly created image row.
        """
        row = self._session.execute(
            text(
                """
                INSERT INTO image (
                    project_id, name, image_path,
                    base_mag, base_width, base_height, deepzoom_tilesize,
                    embedding_x, embedding_y, group_id, train_test_split
                ) VALUES (
                    :project_id, :name, :image_path,
                    :base_mag, :base_width, :base_height, :deepzoom_tilesize,
                    :embedding_x, :embedding_y, :group_id, :train_test_split
                )
                RETURNING *
                """
            ),
            {
                "project_id": project_id,
                "name": name,
                "image_path": image_path,
                "base_mag": base_mag,
                "base_width": base_width,
                "base_height": base_height,
                "deepzoom_tilesize": deepzoom_tilesize,
                "embedding_x": embedding_x,
                "embedding_y": embedding_y,
                "group_id": group_id,
                "train_test_split": train_test_split,
            },
        ).mappings().one()
        return dict(row)

    def list_by_project(self, project_id: int) -> List[Dict[str, Any]]:
        """Return all images belonging to a project ordered by ``image_id``.

        Args:
            project_id: The integer ID of the project.

        Returns:
            A list of dicts, one per image.  Empty list if the project has no
            images.
        """
        rows = self._session.execute(
            text(
                "SELECT * FROM image WHERE project_id = :pid ORDER BY image_id"
            ),
            {"pid": project_id},
        ).mappings().all()
        return [dict(r) for r in rows]

    def delete(self, image_id: int, project_id: int) -> None:
        """Delete an image and all associated patches and predictions.

        Follows the Image Deletion Protocol within the current session's
        transaction:

        1. Reset all ``label_class_id`` values on the project's patches for
           this image to ``1`` (the reserved "Unlabeled" class).
        2. Delete predictions from ``project{N}_pred_patch_latest`` whose
           ``patch_id`` belongs to this image.
        3. Delete predictions from ``project{N}_pred_patch_last`` for the same
           set of patches.
        4. Delete all patches from ``project{N}_patch`` for this image.
        5. Delete the ``image`` row.

        Steps 1–4 must complete before step 5.

        Args:
            image_id: The integer ID of the image to delete.
            project_id: The integer ID of the owning project.  Used to
                resolve project-scoped table names.
        """
        n = project_id
        # Step 1: reset ground-truth labels on affected patches.
        self._session.execute(
            text(
                f"UPDATE project{n}_patch SET label_class_id = 1 WHERE image_id = :image_id"
            ),
            {"image_id": image_id},
        )
        # Step 2 & 3: remove predictions.
        for pred_table in (
            f"project{n}_pred_patch_latest",
            f"project{n}_pred_patch_last",
        ):
            self._session.execute(
                text(
                    f"""
                    DELETE FROM {pred_table}
                    WHERE patch_id IN (
                        SELECT patch_id FROM project{n}_patch WHERE image_id = :image_id
                    )
                    """
                ),
                {"image_id": image_id},
            )
        # Step 4: delete patches.
        self._session.execute(
            text(f"DELETE FROM project{n}_patch WHERE image_id = :image_id"),
            {"image_id": image_id},
        )
        # Step 5: delete the image row.
        self._session.execute(
            text("DELETE FROM image WHERE image_id = :image_id"),
            {"image_id": image_id},
        )
