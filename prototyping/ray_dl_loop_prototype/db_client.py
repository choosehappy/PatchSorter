

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

	def drop_all_tables(self) -> None:
		"""Drop all application tables in reverse dependency order."""
		statements = [
			"DROP TABLE IF EXISTS confusion_matrix_ln CASCADE;",
			"DROP TABLE IF EXISTS pred_patch_latest CASCADE;",
			"DROP TABLE IF EXISTS pred_patch_last CASCADE;",
			"DROP TABLE IF EXISTS patch CASCADE;",
			"DROP TABLE IF EXISTS label_class CASCADE;",
			"DROP TABLE IF EXISTS image CASCADE;",
			"DROP TABLE IF EXISTS settings CASCADE;",
			"DROP TABLE IF EXISTS project CASCADE;",
		]
		with self.get_connection() as conn:
			with conn.cursor() as cur:
				for stmt in statements:
					cur.execute(stmt)

	def setup_schema(self) -> None:
		"""Create all application tables and configure Citus distribution."""
		schema_statements = [
			"""CREATE TABLE IF NOT EXISTS project (
				project_id SERIAL PRIMARY KEY,
				project_name TEXT NOT NULL,
				description TEXT
			);""",
			"""CREATE TABLE IF NOT EXISTS image (
				image_id SERIAL PRIMARY KEY,
				project_id INT NOT NULL REFERENCES project(project_id),
				name TEXT NOT NULL,
				image_path TEXT NOT NULL,
				upload_ts TIMESTAMP NOT NULL,
				base_mag FLOAT NOT NULL,
				base_width INT NOT NULL,
				base_height INT NOT NULL,
				deepzoom_tilesize INT NOT NULL,
				embedding_x FLOAT,
				embedding_y FLOAT,
				group_id INT,
				train_test_split INT,
				UNIQUE(project_id, name)
			);""",
			"""CREATE TABLE IF NOT EXISTS label_class (
				label_class_id SERIAL PRIMARY KEY,
				project_id INT NOT NULL REFERENCES project(project_id),
				name TEXT NOT NULL,
				color_code TEXT,
				event_ts TIMESTAMP NOT NULL,
				UNIQUE(project_id, name)
			);""",
			"""CREATE TABLE IF NOT EXISTS patch (
				patch_id BIGSERIAL PRIMARY KEY,
				patch_uid INT,
				label_class_id SMALLINT NOT NULL,
				image_id INT NOT NULL REFERENCES image(image_id),
				working_mag FLOAT NOT NULL,
				patch_image BYTEA NOT NULL
			);""",
			"""CREATE TABLE IF NOT EXISTS pred_patch_latest (
				patch_id BIGINT PRIMARY KEY,
				embed_x FLOAT NOT NULL,
				embed_y FLOAT NOT NULL,
				grid_cell_i SMALLINT NOT NULL,
				grid_cell_j SMALLINT NOT NULL,
				event_ts TIMESTAMP NOT NULL,
				label_class_id SMALLINT NOT NULL
			);""",
			"""CREATE TABLE IF NOT EXISTS pred_patch_last (
				patch_id BIGINT PRIMARY KEY,
				embed_x FLOAT NOT NULL,
				embed_y FLOAT NOT NULL,
				grid_cell_i SMALLINT NOT NULL,
				grid_cell_j SMALLINT NOT NULL,
				event_ts TIMESTAMP NOT NULL,
				label_class_id SMALLINT NOT NULL
			);""",
			"""CREATE TABLE IF NOT EXISTS settings (
				setting_id SERIAL PRIMARY KEY,
				project_id INT REFERENCES project(project_id),
				setting_key TEXT NOT NULL,
				setting_value TEXT NOT NULL,
				disabled BOOLEAN DEFAULT FALSE
			);""",
			"""CREATE TABLE IF NOT EXISTS confusion_matrix_ln (
				shard_id BIGINT NOT NULL,
				grid_cell_i SMALLINT NOT NULL,
				grid_cell_j SMALLINT NOT NULL,
				bucket_date DATE NOT NULL,
				pred_label SMALLINT NOT NULL,
				gt_label SMALLINT NOT NULL,
				count INT NOT NULL,
				PRIMARY KEY (grid_cell_i, grid_cell_j, pred_label, gt_label, shard_id)
			);""",
		]
		distribution_statements = [
			"SELECT create_reference_table('project');",
			"SELECT create_reference_table('image');",
			"SELECT create_reference_table('label_class');",
			"SELECT create_reference_table('settings');",
			"SELECT create_distributed_table('patch', 'patch_id');",
			"SELECT create_distributed_table('pred_patch_latest', 'patch_id', colocate_with => 'patch');",
			"SELECT create_distributed_table('pred_patch_last', 'patch_id', colocate_with => 'patch');",
			"SELECT create_distributed_table('confusion_matrix_ln', 'shard_id', colocate_with => 'pred_patch_latest');",
		]
		with self.get_connection() as conn:
			with conn.cursor() as cur:
				for stmt in schema_statements:
					cur.execute(stmt)
				for stmt in distribution_statements:
					try:
						cur.execute(stmt)
					except Exception as e:
						print(f"Distribution command failed (may already be distributed): {e}")

	def setup_triggers(
		self,
		patch_table: str = 'patch',
		pred_patch_table: str = 'pred_patch_latest',
		cm_table: str = 'confusion_matrix_ln',
	) -> None:
		"""Install per-shard statement-level triggers for confusion matrix maintenance.

		Trigger A (AFTER INSERT on pred_patch shards): joins new prediction rows with the
		colocated patch shard to obtain gt_label, then upserts aggregated counts into the
		colocated CM shard.

		Trigger B (AFTER UPDATE on patch shards): detects gt_label changes, computes net
		deltas against the colocated pred_patch shard, upserts into the CM shard, and
		removes any rows whose count reaches zero.

		NOTE: TG_ARGV[0] is the schema-qualified CM shard name supplied by
		run_command_on_colocated_placements.  %s (not %I) is used in format() calls so
		that the dot is treated as a schema separator rather than part of the identifier.
		"""
		# Step 1a: INSERT trigger function (pred_patch → CM).
		# Deployed on the coordinator; run_command_on_workers pushes it to all workers.
		# When a patch_id already has a prediction in pred_patch_last (prior epoch),
		# the old CM contribution is decremented and the new one is incremented so that
		# only the net delta is written.  to_regclass() returns NULL when pred_patch_last
		# does not yet exist (first epoch), which falls through to the simple-insert path.
		insert_trigger_fn_sql = f"""
			CREATE OR REPLACE FUNCTION update_cm_shard()
			RETURNS TRIGGER LANGUAGE plpgsql AS $body$
			DECLARE
				v_patch_shard      text;
				v_pred_last_shard  text;
				v_pred_shardid     bigint;
			BEGIN
				-- Extract the numeric shard ID from the current shard table name,
				-- e.g. '{pred_patch_table}_102008' -> 102008
				v_pred_shardid := (regexp_match(TG_TABLE_NAME, '(\\d+)$'))[1]::bigint;

				-- Resolve the colocated {patch_table} shard (same hash-range).
				SELECT TG_TABLE_SCHEMA || '.' || '{patch_table}_' || shardid::text
				INTO v_patch_shard
				FROM pg_dist_shard
				WHERE logicalrelid = '{patch_table}'::regclass
				AND shardminvalue = (
					SELECT shardminvalue FROM pg_dist_shard
					WHERE shardid = v_pred_shardid
				);

				-- Resolve the colocated pred_patch_last shard (same hash-range).
				-- to_regclass() returns NULL if the table does not yet exist,
				-- leaving v_pred_last_shard NULL (no rows matched).
				SELECT TG_TABLE_SCHEMA || '.' || 'pred_patch_last_' || shardid::text
				INTO v_pred_last_shard
				FROM pg_dist_shard
				WHERE logicalrelid = to_regclass(TG_TABLE_SCHEMA || '.pred_patch_last')
				AND shardminvalue = (
					SELECT shardminvalue FROM pg_dist_shard
					WHERE shardid = v_pred_shardid
				);

				-- TG_ARGV[0] = colocated CM shard (schema-qualified).
				IF v_pred_last_shard IS NULL THEN
					-- No prior prediction epoch: simple positive increment.
					EXECUTE format(
						$sql$
						INSERT INTO %s (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label, bucket_date, count)
						SELECT 0, nr.grid_cell_i, nr.grid_cell_j, nr.label_class_id,
							p.label_class_id, CURRENT_DATE, COUNT(*)
						FROM new_rows nr
						INNER JOIN %s p ON nr.patch_id = p.patch_id
						GROUP BY nr.grid_cell_i, nr.grid_cell_j, nr.label_class_id, p.label_class_id
						ON CONFLICT (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label)
						DO UPDATE SET count = EXCLUDED.count + %s.count
						$sql$,
						TG_ARGV[0], v_patch_shard, TG_ARGV[0]
					);
				ELSE
					-- Decrement for superseded predictions in pred_patch_last,
					-- increment for new predictions, net and upsert.
					EXECUTE format(
						$sql$
						WITH
						neg AS (
							SELECT pl.grid_cell_i, pl.grid_cell_j, pl.label_class_id AS pred_label,
								p.label_class_id AS gt_label, -COUNT(*)::bigint AS delta
							FROM new_rows nr
							JOIN %s pl ON pl.patch_id = nr.patch_id
							JOIN %s p  ON p.patch_id  = nr.patch_id
							GROUP BY pl.grid_cell_i, pl.grid_cell_j, pl.label_class_id, p.label_class_id
						),
						pos AS (
							SELECT nr.grid_cell_i, nr.grid_cell_j, nr.label_class_id AS pred_label,
								p.label_class_id AS gt_label, COUNT(*)::bigint AS delta
							FROM new_rows nr
							JOIN %s p ON p.patch_id = nr.patch_id
							GROUP BY nr.grid_cell_i, nr.grid_cell_j, nr.label_class_id, p.label_class_id
						),
						deltas AS (
							SELECT grid_cell_i, grid_cell_j, pred_label, gt_label,
								SUM(delta) AS net_delta
							FROM (SELECT * FROM neg UNION ALL SELECT * FROM pos) t
							GROUP BY grid_cell_i, grid_cell_j, pred_label, gt_label
							HAVING SUM(delta) <> 0
						)
						INSERT INTO %s (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label, bucket_date, count)
						SELECT 0, grid_cell_i, grid_cell_j, pred_label, gt_label, CURRENT_DATE, net_delta
						FROM deltas
						ON CONFLICT (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label)
						DO UPDATE SET count = EXCLUDED.count + %s.count
						$sql$,
						v_pred_last_shard, v_patch_shard, v_patch_shard, TG_ARGV[0], TG_ARGV[0]
					);

					-- Remove any CM rows decremented to zero.
					EXECUTE format('DELETE FROM %s WHERE count = 0', TG_ARGV[0]);
				END IF;
				RETURN NULL;
			END;
			$body$;
			"""

		# Step 1b: UPDATE trigger function (patch gt_label change → CM).
		# Computes negative deltas (old gt_label) and positive deltas (new gt_label),
		# nets them, upserts into the CM shard, then removes rows decremented to zero.
		update_trigger_fn_sql = f"""
			CREATE OR REPLACE FUNCTION update_cm_on_patch_update()
			RETURNS TRIGGER LANGUAGE plpgsql AS $body$
			DECLARE
				v_pred_shard    text;
				v_patch_shardid bigint;
			BEGIN
				-- Extract the numeric shard ID from the patch shard table name.
				v_patch_shardid := (regexp_match(TG_TABLE_NAME, '(\\d+)$'))[1]::bigint;

				-- Resolve the colocated {pred_patch_table} shard (same hash-range).
				SELECT TG_TABLE_SCHEMA || '.' || '{pred_patch_table}_' || shardid::text
				INTO v_pred_shard
				FROM pg_dist_shard
				WHERE logicalrelid = '{pred_patch_table}'::regclass
				AND shardminvalue = (
					SELECT shardminvalue FROM pg_dist_shard
					WHERE shardid = v_patch_shardid
				);

				-- TG_ARGV[0] = colocated CM shard (schema-qualified).
				-- Only process rows where label_class_id actually changed.
				EXECUTE format(
					$sql$
					WITH changed AS (
						SELECT o.patch_id,
							o.label_class_id AS old_gt,
							n.label_class_id AS new_gt
						FROM old_rows o
						JOIN new_rows n ON o.patch_id = n.patch_id
						WHERE o.label_class_id IS DISTINCT FROM n.label_class_id
					),
					neg AS (
						SELECT pp.grid_cell_i, pp.grid_cell_j, pp.label_class_id AS pred_label,
							c.old_gt AS gt_label, -COUNT(*)::bigint AS delta
						FROM changed c
						JOIN %s pp ON pp.patch_id = c.patch_id
						GROUP BY pp.grid_cell_i, pp.grid_cell_j, pp.label_class_id, c.old_gt
					),
					pos AS (
						SELECT pp.grid_cell_i, pp.grid_cell_j, pp.label_class_id AS pred_label,
							c.new_gt AS gt_label, COUNT(*)::bigint AS delta
						FROM changed c
						JOIN %s pp ON pp.patch_id = c.patch_id
						GROUP BY pp.grid_cell_i, pp.grid_cell_j, pp.label_class_id, c.new_gt
					),
					deltas AS (
						SELECT grid_cell_i, grid_cell_j, pred_label, gt_label,
							SUM(delta) AS net_delta
						FROM (SELECT * FROM neg UNION ALL SELECT * FROM pos) t
						GROUP BY grid_cell_i, grid_cell_j, pred_label, gt_label
						HAVING SUM(delta) <> 0
					)
					INSERT INTO %s (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label, bucket_date, count)
					SELECT 0, grid_cell_i, grid_cell_j, pred_label, gt_label, CURRENT_DATE, net_delta
					FROM deltas
					ON CONFLICT (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label)
					DO UPDATE SET count = %s.count + EXCLUDED.count
					$sql$,
					v_pred_shard, v_pred_shard, TG_ARGV[0], TG_ARGV[0]
				);

				-- Remove any CM rows that have been decremented to zero.
				EXECUTE format('DELETE FROM %s WHERE count = 0', TG_ARGV[0]);

				RETURN NULL;
			END;
			$body$;
			"""

		# Step 2a: Attach a per-shard AFTER INSERT trigger to each pred_patch shard.
		attach_insert_triggers_sql = f"""
			SELECT run_command_on_colocated_placements(
				'{pred_patch_table}',
				'{cm_table}',
				$cmd$
					CREATE TRIGGER trg_update_cm AFTER INSERT ON %s
					REFERENCING NEW TABLE AS new_rows
					FOR EACH STATEMENT
					EXECUTE FUNCTION update_cm_shard(%L)
				$cmd$
			);
			"""

		# Step 2b: Attach a per-shard AFTER UPDATE trigger to each patch shard.
		attach_update_triggers_sql = f"""
			SELECT run_command_on_colocated_placements(
				'{patch_table}',
				'{cm_table}',
				$cmd$
					CREATE TRIGGER trg_update_cm_on_patch_update AFTER UPDATE ON %s
					REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
					FOR EACH STATEMENT
					EXECUTE FUNCTION update_cm_on_patch_update(%L)
				$cmd$
			);
			"""

		with self.get_connection() as conn:
			with conn.cursor() as cur:
				cur.execute(insert_trigger_fn_sql)
				cur.execute(f"SELECT run_command_on_workers($outer${insert_trigger_fn_sql}$outer$);")
				print("INSERT trigger function created on coordinator and workers.")

				cur.execute(update_trigger_fn_sql)
				cur.execute(f"SELECT run_command_on_workers($outer${update_trigger_fn_sql}$outer$);")
				print("UPDATE trigger function created on coordinator and workers.")

				cur.execute(attach_insert_triggers_sql)
				print(f"Per-shard INSERT triggers installed on {pred_patch_table} shards.")

				cur.execute(attach_update_triggers_sql)
				print(f"Per-shard UPDATE triggers installed on {patch_table} shards.")

		print("\nAll per-shard triggers installed.")


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

	def __init__(self, client: CitusHeadClient, cm_table: str = 'confusion_matrix_ln'):
		self.client = client
		self.cm_table = cm_table

	def rotate_tables(self) -> None:
		"""
		Drop pred_patch_last, promote pred_patch_latest -> pred_patch_last,
		and create a fresh empty pred_patch_latest.

		The per-shard INSERT trigger is re-attached to the new pred_patch_latest shards
		because CREATE TABLE produces a trigger-free table; the old trigger travelled
		with the renamed pred_patch_last and cannot be inherited.
		"""
		# Re-attach trigger SQL built once and reused for run_command_on_colocated_placements.
		attach_trigger_sql = f"""
			SELECT run_command_on_colocated_placements(
				'pred_patch_latest',
				'{self.cm_table}',
				$cmd$
					CREATE TRIGGER trg_update_cm AFTER INSERT ON %s
					REFERENCING NEW TABLE AS new_rows
					FOR EACH STATEMENT
					EXECUTE FUNCTION update_cm_shard(%L)
				$cmd$
			);
			"""

		with self.client.get_connection() as conn:
			with conn.cursor() as cur:
				cur.execute("DROP TABLE IF EXISTS pred_patch_last CASCADE;")
				cur.execute("ALTER TABLE pred_patch_latest RENAME TO pred_patch_last;")
				cur.execute("SELECT run_command_on_shards('pred_patch_last', 'DROP TRIGGER IF EXISTS trg_update_cm ON %s');")
				cur.execute(self._CREATE_PRED_PATCH_LATEST_SQL)
				cur.execute("SELECT create_distributed_table('pred_patch_latest', 'patch_id');")
				cur.execute(attach_trigger_sql)


