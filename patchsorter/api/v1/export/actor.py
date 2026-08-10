from __future__ import annotations

import csv

import ray
from sqlalchemy import text

from patchsorter.db.head_client import get_client
from patchsorter.utils.fsmanager import FileStoreManager
from .models import ExportImage

@ray.remote
def _export_patch_csv(
    image: ExportImage,
    project_id: int,
    session_id: str,
    batch_size: int = 1000,
) -> None:
    """Export patch labels for a single image as a CSV file.

    Uses cursor-based pagination on patch_id to avoid loading all rows into
    memory at once.

    Each CSV matches the import patch CSV format (compatible with CsvGeometryIterable
    and HybridPatchIterable): columns are `patch_id, patch_uid, label_class_id`.
    Filename follows the convention `patches_{image_id}.csv` to match the download URL.
    """
    fsman = FileStoreManager()
    session_dir = fsman.export.get_session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)

    csv_filename = f"patches_{image.image_id}.csv"
    csv_path = session_dir / csv_filename

    with get_client().get_session() as session:
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["patch_id", "patch_uid", "label_class_id"])

            cursor: int | None = None
            while True:
                query = text(
                    f"SELECT patch_id, patch_uid, label_class_id "
                    f"FROM project{project_id}_patch "
                    f"WHERE image_id = :image_id "
                    f"  AND (:cursor IS NULL OR patch_id > :cursor) "
                    f"ORDER BY patch_id ASC "
                    f"LIMIT :limit"
                )
                params = {"image_id": image.image_id, "cursor": cursor, "limit": batch_size}
                rows = session.execute(query, params).fetchall()

                if not rows:
                    break

                for row in rows:
                    writer.writerow([row[0], row[1], row[2]])

                cursor = rows[-1][0]
                if len(rows) < batch_size:
                    break


@ray.remote(max_concurrency=1)
class ExportSessionActor:
    """Per-session Ray actor that owns export paths and dispatches CSV generation tasks.

    Uses ``max_concurrency=1`` (concurrency=1) because the actor processes a single export
    session at a time.
    """

    def __init__(self, project_id: int, session_id: str) -> None:
        self._project_id = project_id
        self._session_id = session_id
        self._fsman = FileStoreManager()
        self._fsman.export.create_session_dir(session_id)

    def __ray_shutdown__(self) -> None:
        try:
            self._fsman.export.cleanup_session(self._session_id)
        except Exception:
            pass

    def dispatch_tasks(self, images: list[ExportImage]) -> None:
        """Dispatch _export_patch_csv once per image.

        Each call to ``_export_patch_csv.remote()`` creates a Ray child task
        that can be tracked via ``TaskChildrenGrid``. Each child task is named
        using the image name for visibility in the task grid.

        Args:
            images: List of ``ExportImage`` dataclasses with ``image_id`` and
                ``image_name`` attributes.

        Blocks until all child tasks complete.
        """
        # Dispatch one child task per image, naming each for visibility
        child_refs = [
            _export_patch_csv
                .options(name=f"Export {img.image_name}")
                .remote(img, self._project_id, self._session_id)
            for img in images
        ]

        # Block until all child tasks complete
        ray.get(child_refs)

    def get_csv_path(self, image_id: int) -> str:
        """Return the full path to a CSV file for the given image_id.

        Used by the download endpoint to locate files.
        """
        csv_filename = f"patches_{image_id}.csv"
        return str(self._fsman.export.get_session_dir(self._session_id) / csv_filename)
