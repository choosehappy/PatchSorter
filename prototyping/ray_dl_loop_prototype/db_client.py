

import psycopg
from psycopg.rows import dict_row
from typing import Any, Dict, List, Optional
from constants import (
    CITUS_HEAD_HOST, CITUS_HEAD_PORT, CITUS_HEAD_DB, CITUS_HEAD_USER, CITUS_HEAD_PASSWORD
)



class CitusHeadClient:
	"""SDK for interacting with the Citus/Postgres node (single-node setup)."""
	def __init__(self, host=None, port=None, dbname=None, user=None, password=None):
		self.host = host or CITUS_HEAD_HOST
		self.port = port or CITUS_HEAD_PORT
		self.dbname = dbname or CITUS_HEAD_DB
		self.user = user or CITUS_HEAD_USER
		self.password = password or CITUS_HEAD_PASSWORD
		self.conn_str = f"host={self.host} port={self.port} dbname={self.dbname} user={self.user} password={self.password}"

	def get_connection(self):
		return psycopg.connect(self.conn_str, autocommit=True, row_factory=dict_row)

	def fetch_patches(self, limit=10) -> List[Dict[str, Any]]:
		with self.get_connection() as conn:
			with conn.cursor() as cur:
				cur.execute("SELECT * FROM patch LIMIT %s;", (limit,))
				return cur.fetchall()

	def insert_patch(self, patch_uid: int, label_class_id: int, image_id: int, working_mag: float, patch_image: bytes) -> int:
		with self.get_connection() as conn:
			with conn.cursor() as cur:
				cur.execute(
					"""
					INSERT INTO patch (patch_uid, label_class_id, image_id, working_mag, patch_image)
					VALUES (%s, %s, %s, %s, %s)
					RETURNING patch_id;
					""",
					(patch_uid, label_class_id, image_id, working_mag, patch_image)
				)
				return cur.fetchone()['patch_id']

	def fetch_patches_by_shards(self, shard_ids: List[int]) -> List[Dict[str, Any]]:
		"""Fetch all patches from specific Citus shard tables directly."""
		rows = []
		with self.get_connection() as conn:
			with conn.cursor() as cur:
				for shard_id in shard_ids:
					cur.execute(f"SELECT * FROM public.patch_{shard_id};")
					rows.extend(cur.fetchall())
		return rows

	# Optionally, keep this for Citus introspection, but not required for single-node
	def get_worker_nodes(self) -> List[Dict[str, Any]]:
		with self.get_connection() as conn:
			with conn.cursor() as cur:
				cur.execute("SELECT * FROM citus_get_active_worker_nodes();")
				return cur.fetchall()


