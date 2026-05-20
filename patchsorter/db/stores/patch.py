from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session


class PatchStore:
    """Data-access methods for a project's ``project{N}_patch`` distributed table.

    All operations target the table ``project{project_id}_patch`` whose rows
    are distributed across Citus shards by ``patch_id``.

    Args:
        project_id: Integer ID of the project.  Used to construct the
            project-scoped table name.
        session: An active SQLAlchemy session provided by
            :meth:`~patchsorter.db.db_client.CitusHeadClient.get_session` or
            :meth:`~patchsorter.db.db_client.CitusWorkerClient.get_session`.
    """

    def __init__(self, project_id: int, session: Session) -> None:
        self.project_id = project_id
        self._session = session
        self.table_name = f"project{project_id}_patch"

    def insert(
        self,
        patch_uid: int,
        label_class_id: int,
        image_id: int,
        working_mag: float,
        patch_image: bytes,
    ) -> int:
        """Insert a single patch and return the generated ``patch_id``.

        Args:
            patch_uid: External integer identifier for the patch.
            label_class_id: Ground-truth label class for the patch.
            image_id: Foreign key to the parent image.
            working_mag: Magnification level at which the patch was extracted.
            patch_image: Raw image bytes (JPEG/PNG/etc.).

        Returns:
            The ``patch_id`` assigned by the database.
        """
        row = self._session.execute(
            text(
                f"""
                INSERT INTO {self.table_name}
                    (patch_uid, label_class_id, image_id, working_mag, patch_image)
                VALUES (:patch_uid, :label_class_id, :image_id, :working_mag, :patch_image)
                RETURNING patch_id
                """
            ),
            {
                "patch_uid": patch_uid,
                "label_class_id": label_class_id,
                "image_id": image_id,
                "working_mag": working_mag,
                "patch_image": patch_image,
            },
        ).mappings().one()
        return row["patch_id"]

    def bulk_insert(self, records: List[tuple]) -> int:
        """Insert multiple patches in a single round-trip.

        Each element of *records* must be a tuple of::

            (patch_uid, label_class_id, image_id, working_mag, patch_image)

        The insert uses ``executemany`` which sends all rows to the server in
        a single network round-trip (psycopg3 pipeline mode).

        Args:
            records: List of 5-tuples describing the patches to insert.

        Returns:
            The number of rows inserted (equal to ``len(records)``).
        """
        from psycopg.rows import dict_row  # raw connection needed for executemany

        # executemany is not natively supported through SQLAlchemy text() for
        # bulk-insert performance, so we fall back to a VALUES list approach.
        if not records:
            return 0
        placeholders = ", ".join(
            [
                f"(:patch_uid_{i}, :label_class_id_{i}, :image_id_{i}, :working_mag_{i}, :patch_image_{i})"
                for i in range(len(records))
            ]
        )
        params: Dict[str, Any] = {}
        for i, (pu, lc, im, wm, pi) in enumerate(records):
            params[f"patch_uid_{i}"] = pu
            params[f"label_class_id_{i}"] = lc
            params[f"image_id_{i}"] = im
            params[f"working_mag_{i}"] = wm
            params[f"patch_image_{i}"] = pi

        self._session.execute(
            text(
                f"""
                INSERT INTO {self.table_name}
                    (patch_uid, label_class_id, image_id, working_mag, patch_image)
                VALUES {placeholders}
                """
            ),
            params,
        )
        return len(records)

    def fetch(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch up to *limit* patches, ordered by ``patch_id``.

        Args:
            limit: Maximum number of rows to return.  Defaults to ``10``.

        Returns:
            A list of dicts, one per patch row (excluding ``patch_image`` blob).
        """
        rows = self._session.execute(
            text(
                f"""
                SELECT patch_id, patch_uid, label_class_id, image_id, working_mag
                FROM {self.table_name}
                ORDER BY patch_id
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).mappings().all()
        return [dict(r) for r in rows]

    def fetch_by_shards(self, shard_ids: List[int]) -> List[Dict[str, Any]]:
        """Fetch all patches from specific Citus physical shard tables.

        This bypasses the coordinator routing and reads directly from the
        named shard objects.  Useful when running on a worker node via
        :meth:`~patchsorter.db.db_client.CitusWorkerClient.get_session`.

        Args:
            shard_ids: List of numeric Citus shard IDs to query.

        Returns:
            A list of dicts with patch metadata (no ``patch_image`` blob).
        """
        rows: List[Dict[str, Any]] = []
        for shard_id in shard_ids:
            shard_rows = self._session.execute(
                text(
                    f"SELECT patch_id, patch_uid, label_class_id, image_id, working_mag FROM {self.table_name}_{shard_id}"
                )
            ).mappings().all()
            rows.extend(dict(r) for r in shard_rows)
        return rows

    def update_label(self, patch_id: int, label_class_id: int) -> None:
        """Update the ground-truth label of a single patch.

        Changing ``label_class_id`` fires the ``AFTER UPDATE`` trigger on the
        patch shard, which propagates the delta to all co-located
        confusion-matrix shards automatically.

        Args:
            patch_id: The ``patch_id`` of the patch to relabel.
            label_class_id: The new ground-truth label class.
        """
        self._session.execute(
            text(
                f"""
                UPDATE {self.table_name}
                SET label_class_id = :label_class_id
                WHERE patch_id = :patch_id
                """
            ),
            {"patch_id": patch_id, "label_class_id": label_class_id},
        )
