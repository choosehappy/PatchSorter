from patchsorter.db.db_client import CitusHeadClient


class PredPatchStore:
	"""Manages the pred_patch_latest and pred_patch_last tables."""

	_CREATE_PRED_PATCH_LATEST_SQL = """
		CREATE TABLE pred_patch_latest (
			patch_id BIGINT PRIMARY KEY,
			embed_x FLOAT NOT NULL,
			embed_y FLOAT NOT NULL,
			grid_cell_i SMALLINT NOT NULL,
			grid_cell_j SMALLINT NOT NULL,
			event_ts TIMESTAMP NOT NULL,
			label_class_id SMALLINT NOT NULL
		);
	"""

	def __init__(self, client: CitusHeadClient):
		self.client = client

	def rotate_tables(self) -> None:
		"""
		Rotate pred_patch_latest → pred_patch_last via a 3-way rename.

		No rows are copied and no tables are created or dropped. Triggers are not
		registered or destroyed here — they travel with their physical shard objects.

		Steps:
		  1. TRUNCATE pred_patch_last        (free stale data; this shard set becomes new pred_patch_latest)
		  2. RENAME pred_patch_last  → pred_patch_tmp
		  3. RENAME pred_patch_latest → pred_patch_last   (current cycle's predictions become "last")
		  4. RENAME pred_patch_tmp   → pred_patch_latest  (empty recycled shards become the new "latest")

		All four statements execute inside a single atomic transaction.
		"""
		with self.client.get_connection() as conn:
			with conn.cursor() as cur:
				cur.execute("TRUNCATE TABLE pred_patch_last;")
				cur.execute("ALTER TABLE pred_patch_last RENAME TO pred_patch_tmp;")
				cur.execute("ALTER TABLE pred_patch_latest RENAME TO pred_patch_last;")
				cur.execute("ALTER TABLE pred_patch_tmp RENAME TO pred_patch_latest;")