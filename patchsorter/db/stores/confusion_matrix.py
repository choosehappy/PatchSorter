from patchsorter.db.db_client import CitusHeadClient


import numpy as np


from typing import Tuple


class ConfusionMatrixStore:
	"""Reads aggregated patch label counts from confusion_matrix_l{level} tables.

	These tables are maintained by per-shard triggers and have the schema:
		shard_id     bigint
		grid_cell_i  smallint
		grid_cell_j  smallint
		bucket_date  date
		pred_label   smallint
		gt_label     smallint
		count        int

	Because counts are split across Citus shards, bbox_search collapses
	shard_id with SUM(count) GROUP BY (gt_label, pred_label, grid_cell_i, grid_cell_j).
	"""

	def __init__(self, level: int, client: "CitusHeadClient") -> None:
		self.level = level
		self.client = client
		self.table_name = f"confusion_matrix_l{level}"

	def bbox_search(self, bbox, label_pairs) -> np.ndarray:
		"""Return (N, 5) int32 array: [gt_label, pred_label, grid_cell_i, grid_cell_j, count]."""
		i_min, j_min, i_max, j_max = bbox
		if len(label_pairs) == 0:
			return np.empty((0, 5), dtype=np.int32)

		flat_pairs = [v for gt, pred in label_pairs for v in (int(gt), int(pred))]
		pair_placeholders = ", ".join(["(%s, %s)"] * len(label_pairs))
		with self.client.get_connection() as conn:
			with conn.cursor() as cur:
				cur.execute(
					f"""
					SELECT gt_label, pred_label, grid_cell_i, grid_cell_j,
					       SUM(count)::int AS patch_count
					FROM {self.table_name}
					WHERE grid_cell_i BETWEEN %s AND %s
					  AND grid_cell_j BETWEEN %s AND %s
					  AND (gt_label, pred_label) IN ({pair_placeholders})
					GROUP BY gt_label, pred_label, grid_cell_i, grid_cell_j
					""",
					[i_min, i_max, j_min, j_max] + flat_pairs,
				)
				rows = cur.fetchall()
		if not rows:
			return np.empty((0, 5), dtype=np.int32)
		return np.array([[r["gt_label"], r["pred_label"], r["grid_cell_i"], r["grid_cell_j"], r["patch_count"]] for r in rows], dtype=np.int32)

	def read_region(
		self, bbox, label_pairs, sum_over_gt: bool = True
	) -> Tuple[np.ndarray, np.ndarray]:
		"""Return (region, class_indices) arrays for rendering a tile.

		If sum_over_gt=True  → region shape (n_pred, n_i, n_j), class_indices = pred_labels.
		If sum_over_gt=False → region shape (n_gt,   n_i, n_j), class_indices = gt_labels.
		"""
		i_min, j_min, i_max, j_max = bbox
		n_i = i_max - i_min + 1
		n_j = j_max - j_min + 1

		rows = self.bbox_search(bbox, label_pairs)

		lp = np.array(label_pairs, dtype=np.int32)
		gt_labels = np.unique(lp[:, 0])
		pred_labels = np.unique(lp[:, 1])

		gt_lookup = np.full(gt_labels.max() + 1, -1, dtype=np.int32)
		pred_lookup = np.full(pred_labels.max() + 1, -1, dtype=np.int32)
		gt_lookup[gt_labels] = np.arange(len(gt_labels))
		pred_lookup[pred_labels] = np.arange(len(pred_labels))

		mat = np.zeros((len(gt_labels), len(pred_labels), n_i, n_j), dtype=np.int32)
		if len(rows) > 0:
			mat[
				gt_lookup[rows[:, 0]],
				pred_lookup[rows[:, 1]],
				rows[:, 2] - i_min,
				rows[:, 3] - j_min,
			] = rows[:, 4]

		if sum_over_gt:
			return mat.sum(axis=0), pred_labels
		else:
			return mat.sum(axis=1), gt_labels

	def read_confusion_matrix(
		self, bbox, label_pairs
	) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
		"""Return (confusion, gt_labels, pred_labels) summed over spatial dimensions.

		confusion shape: (n_gt, n_pred).
		"""
		i_min, j_min, i_max, j_max = bbox
		n_i = i_max - i_min + 1
		n_j = j_max - j_min + 1

		rows = self.bbox_search(bbox, label_pairs)

		lp = np.array(label_pairs, dtype=np.int32)
		gt_labels = np.unique(lp[:, 0])
		pred_labels = np.unique(lp[:, 1])

		gt_lookup = np.full(gt_labels.max() + 1, -1, dtype=np.int32)
		pred_lookup = np.full(pred_labels.max() + 1, -1, dtype=np.int32)
		gt_lookup[gt_labels] = np.arange(len(gt_labels))
		pred_lookup[pred_labels] = np.arange(len(pred_labels))

		mat = np.zeros((len(gt_labels), len(pred_labels), n_i, n_j), dtype=np.int64)
		if len(rows) > 0:
			mat[
				gt_lookup[rows[:, 0]],
				pred_lookup[rows[:, 1]],
				rows[:, 2] - i_min,
				rows[:, 3] - j_min,
			] = rows[:, 4]

		confusion = mat.sum(axis=(2, 3))  # (n_gt, n_pred)
		return confusion, gt_labels, pred_labels

	def get_max_counts(self, bbox, label_pairs, num_classes: int) -> np.ndarray:
		"""Return (num_classes, num_classes) array of per-cell max counts per (gt, pred) pair."""
		i_min, j_min, i_max, j_max = bbox
		if len(label_pairs) == 0:
			return np.zeros((num_classes, num_classes), dtype=np.float32)

		flat_pairs = [v for gt, pred in label_pairs for v in (int(gt), int(pred))]
		pair_placeholders = ", ".join(["(%s, %s)"] * len(label_pairs))
		with self.client.get_connection() as conn:
			with conn.cursor() as cur:
				cur.execute(
					f"""
					SELECT gt_label, pred_label, MAX(cell_sum) AS max_count
					FROM (
						SELECT gt_label, pred_label, grid_cell_i, grid_cell_j,
						       SUM(count) AS cell_sum
						FROM {self.table_name}
						WHERE gt_label IS NOT NULL
						  AND grid_cell_i BETWEEN %s AND %s
						  AND grid_cell_j BETWEEN %s AND %s
						  AND (gt_label, pred_label) IN ({pair_placeholders})
						GROUP BY gt_label, pred_label, grid_cell_i, grid_cell_j
					) sub
					GROUP BY gt_label, pred_label
					""",
					[i_min, i_max, j_min, j_max] + flat_pairs,
				)
				rows = cur.fetchall()

		mat = np.zeros((num_classes, num_classes), dtype=np.float32)
		for row in rows:
			gt, pred, count = row["gt_label"], row["pred_label"], row["max_count"]
			if 0 <= gt < num_classes and 0 <= pred < num_classes:
				mat[gt, pred] = count
		return mat