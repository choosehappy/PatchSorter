
from psycopg.rows import dict_row
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from typing import Any, Dict, List, Optional
from patchsorter.db.constants import (
    CITUS_HEAD_HOST, CITUS_HEAD_PORT, CITUS_HEAD_DB, CITUS_HEAD_USER, CITUS_HEAD_PASSWORD
)



class CitusHeadClient:
	"""SDK for interacting with the Citus/Postgres node (single-node setup)."""
	def __init__(self, host=CITUS_HEAD_HOST, port=CITUS_HEAD_PORT, dbname=CITUS_HEAD_DB, user=CITUS_HEAD_USER, password=CITUS_HEAD_PASSWORD):
		self.engine = create_engine(
			URL.create(
				drivername="postgresql+psycopg",
				username=user,
				password=password,
				host=host,
				port=port,
				database=dbname,
			),
			pool_size=10,
		)

	def get_connection(self):
		"""Raw psycopg connection for Citus DDL, triggers, shard ops."""
		return self.engine.raw_connection()

	def get_sa_connection(self):
		"""SQLAlchemy Core connection for normal queries."""
		return self.engine.connect()

	def fetch_patches(self, limit=10) -> List[Dict[str, Any]]:
		with self.get_connection() as conn:
			with conn.cursor(row_factory=dict_row) as cur:
				cur.execute("SELECT * FROM patch LIMIT %s;", (limit,))
				return cur.fetchall()

	def insert_patch(self, patch_uid: int, label_class_id: int, image_id: int, working_mag: float, patch_image: bytes) -> int:
		with self.get_connection() as conn:
			with conn.cursor(row_factory=dict_row) as cur:
				cur.execute(
					"""
					INSERT INTO patch (patch_uid, label_class_id, image_id, working_mag, patch_image)
					VALUES (%s, %s, %s, %s, %s)
					RETURNING patch_id;
					""",
					(patch_uid, label_class_id, image_id, working_mag, patch_image)
				)
				return cur.fetchone()['patch_id']

	def bulk_insert_patches(self, records: List[tuple]) -> int:
		"""Insert multiple patches in a single round-trip using executemany.

		Each record in *records* must be a tuple of
		(patch_uid, label_class_id, image_id, working_mag, patch_image).

		Returns the number of rows inserted.
		"""
		with self.get_connection() as conn:
			with conn.cursor(row_factory=dict_row) as cur:
				cur.executemany(
					"""
					INSERT INTO patch (patch_uid, label_class_id, image_id, working_mag, patch_image)
					VALUES (%s, %s, %s, %s, %s);
					""",
					records,
				)
				return len(records)

	def fetch_patches_by_shards(self, shard_ids: List[int]) -> List[Dict[str, Any]]:
		"""Fetch all patches from specific Citus shard tables directly."""
		rows = []
		with self.get_connection() as conn:
			with conn.cursor(row_factory=dict_row) as cur:
				for shard_id in shard_ids:
					cur.execute(f"SELECT * FROM public.patch_{shard_id};")
					rows.extend(cur.fetchall())
		return rows

	# Optionally, keep this for Citus introspection, but not required for single-node
	def get_worker_nodes(self) -> List[Dict[str, Any]]:
		with self.get_connection() as conn:
			with conn.cursor(row_factory=dict_row) as cur:
				cur.execute("SELECT * FROM citus_get_active_worker_nodes();")
				return cur.fetchall()

	def drop_all_tables(self) -> None:
		"""Drop all application tables in reverse dependency order."""
		statements = [
			"DROP TABLE IF EXISTS confusion_matrix_l8 CASCADE;",
			"DROP TABLE IF EXISTS confusion_matrix_l9 CASCADE;",
			"DROP TABLE IF EXISTS confusion_matrix_l10 CASCADE;",
			"DROP TABLE IF EXISTS confusion_matrix_l11 CASCADE;",
			"DROP TABLE IF EXISTS confusion_matrix_l12 CASCADE;",
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
			*[f"""CREATE TABLE IF NOT EXISTS confusion_matrix_l{lvl} (
				shard_id BIGINT NOT NULL,
				grid_cell_i SMALLINT NOT NULL,
				grid_cell_j SMALLINT NOT NULL,
				bucket_date DATE NOT NULL,
				pred_label SMALLINT NOT NULL,
				gt_label SMALLINT NOT NULL,
				count INT NOT NULL,
				PRIMARY KEY (grid_cell_i, grid_cell_j, pred_label, gt_label, shard_id)
			);""" for lvl in range(8, 13)],
		]
		distribution_statements = [
			"SELECT create_reference_table('project');",
			"SELECT create_reference_table('image');",
			"SELECT create_reference_table('label_class');",
			"SELECT create_reference_table('settings');",
			"SELECT create_distributed_table('patch', 'patch_id');",
			"SELECT create_distributed_table('pred_patch_latest', 'patch_id', colocate_with => 'patch');",
			"SELECT create_distributed_table('pred_patch_last', 'patch_id', colocate_with => 'patch');",
			*[f"SELECT create_distributed_table('confusion_matrix_l{lvl}', 'shard_id', colocate_with => 'patch');" for lvl in range(8, 13)],
			*[f"CREATE INDEX IF NOT EXISTS idx_cm_l{lvl}_nonpositive ON confusion_matrix_l{lvl} (count) WHERE count <= 0;" for lvl in range(8, 13)],
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
	) -> None:
		"""Install per-shard statement-level triggers for hierarchical confusion matrix maintenance.

		Five CM tables (confusion_matrix_l8 through confusion_matrix_l12) are maintained in
		lock-step.  l12 stores raw (finest-level) grid cell counts; each coarser level
		right-shifts grid_cell_i/j by one additional bit relative to l12.

		Trigger A (AFTER INSERT on pred_patch shards): joins new prediction rows with the
		colocated patch shard to obtain gt_label, then upserts aggregated counts into all
		five colocated CM shards in a single loop.

		Trigger B (AFTER UPDATE on patch shards): detects gt_label changes, computes net
		deltas against the colocated pred_patch shard, upserts into all five CM shards,
		and removes rows whose count reaches zero or below.

		Both trigger functions resolve their target CM shards dynamically from pg_dist_shard
		using the shardminvalue of the firing shard — no TG_ARGV required.
		"""
		# Step 1a: INSERT trigger function (pred_patch → all CM levels).
		# Loops over l8..l12 inside the trigger body.  For each level the colocated
		# CM shard is resolved dynamically from pg_dist_shard using v_shardminvalue.
		# The bit-shift (12 - level) maps l12 grid_cell_i/j down to coarser levels.
		#
		# Key optimisation: SET LOCAL enable_nestloop = off at entry forces the planner
		# to use hash joins for all joins in this trigger invocation.  This prevents the
		# catastrophic nested-loop plans that arise because the planner cannot estimate
		# the cardinality of transition table (new_rows) references inside EXECUTE blocks.
		# No DDL (CREATE/DROP TEMP TABLE) is used — Citus blocks DDL in shard triggers.
		insert_trigger_fn_sql = f"""
			CREATE OR REPLACE FUNCTION update_cm_shard()
			RETURNS TRIGGER LANGUAGE plpgsql AS $body$
			DECLARE
				v_patch_shard         text;
				v_pred_last_shard     text;
				v_pred_last_regclass  regclass;
				v_pred_shardid        bigint;
				v_patch_shardid       bigint;
				v_shardminvalue       text;
				v_cm_shard            text;
				v_lvl                 int;
				v_shift               int;
			BEGIN
				-- Disable nested loops for this transaction so the planner is forced to
				-- use hash joins even though it cannot estimate new_rows cardinality.
				SET LOCAL enable_nestloop = off;

				-- Extract the numeric shard ID from the current shard table name,
				-- e.g. '{pred_patch_table}_102008' -> 102008
				v_pred_shardid := (regexp_match(TG_TABLE_NAME, '(\\d+)$'))[1]::bigint;

				SELECT shardminvalue INTO v_shardminvalue FROM pg_dist_shard WHERE shardid = v_pred_shardid;

				-- Resolve the colocated {patch_table} shard (same hash-range).
				SELECT TG_TABLE_SCHEMA || '.' || '{patch_table}_' || shardid::text
				INTO v_patch_shard
				FROM pg_dist_shard
				WHERE logicalrelid = '{patch_table}'::regclass
				AND shardminvalue = v_shardminvalue;

				-- Extract the stable patch shard ID to use as shard_id in CM rows.
				-- Using the patch shard ID (not the pred shard ID) ensures ON CONFLICT
				-- correctly matches rows written in previous cycles after a table rotation.
				v_patch_shardid := (regexp_match(v_patch_shard, '(\\d+)$'))[1]::bigint;

				-- Resolve the colocated pred_patch_last shard (same hash-range).
				-- to_regclass() returns NULL if the table does not yet exist.
				v_pred_last_regclass := to_regclass(TG_TABLE_SCHEMA || '.pred_patch_last');
				SELECT TG_TABLE_SCHEMA || '.' || 'pred_patch_last_' || shardid::text
				INTO v_pred_last_shard
				FROM pg_dist_shard
				WHERE logicalrelid = v_pred_last_regclass
				AND shardminvalue = v_shardminvalue;

				IF v_pred_last_regclass IS NOT NULL AND v_pred_last_shard IS NULL THEN
					RAISE EXCEPTION 'could not resolve pred_patch_last shard for pred shardid %', v_pred_shardid;
				END IF;

				-- Write to each CM level (l8 coarsest through l12 finest).
				-- shift = 12 - level maps finest-level i/j to the target level.
				FOR v_lvl IN 8..12 LOOP
					v_shift := 12 - v_lvl;

					SELECT TG_TABLE_SCHEMA || '.' || 'confusion_matrix_l' || v_lvl::text || '_' || shardid::text
					INTO v_cm_shard
					FROM pg_dist_shard
					WHERE logicalrelid = ('confusion_matrix_l' || v_lvl::text)::regclass
					AND shardminvalue = v_shardminvalue;

					IF v_pred_last_shard IS NULL THEN
						-- No prior prediction epoch: simple positive increment.
						-- Plain JOIN (no LATERAL) against the patch shard.
						EXECUTE format(
							$sql$
							INSERT INTO %s (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label, bucket_date, count)
							SELECT $1,
								(nr.grid_cell_i >> $2)::smallint,
								(nr.grid_cell_j >> $2)::smallint,
								nr.label_class_id,
								p.label_class_id,
								CURRENT_DATE,
								COUNT(*)
							FROM new_rows nr
							JOIN %s p ON p.patch_id = nr.patch_id
							GROUP BY (nr.grid_cell_i >> $2), (nr.grid_cell_j >> $2), nr.label_class_id, p.label_class_id
							ON CONFLICT (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label)
							DO UPDATE SET count = EXCLUDED.count + %s.count, bucket_date = CURRENT_DATE
							$sql$,
							v_cm_shard, v_patch_shard, v_cm_shard
						) USING v_patch_shardid, v_shift;
					ELSE
						-- Decrement for superseded predictions, increment for new, net and upsert.
						-- gt is MATERIALIZED so the patch join executes once; neg and pos both
						-- reference new_rows which gets hash-joined (nestloop is disabled).
						EXECUTE format(
							$sql$
							WITH
							gt AS MATERIALIZED (
								SELECT nr.patch_id, p.label_class_id AS gt_label
								FROM new_rows nr
								JOIN %s p ON p.patch_id = nr.patch_id
							),
							neg AS (
								SELECT (pl.grid_cell_i >> $2)::smallint AS grid_cell_i,
									(pl.grid_cell_j >> $2)::smallint AS grid_cell_j,
									pl.label_class_id AS pred_label,
									g.gt_label,
									-COUNT(*)::bigint AS delta
								FROM new_rows nr
								JOIN %s pl ON pl.patch_id = nr.patch_id
								JOIN gt g ON g.patch_id = nr.patch_id
								GROUP BY (pl.grid_cell_i >> $2), (pl.grid_cell_j >> $2), pl.label_class_id, g.gt_label
							),
							pos AS (
								SELECT (nr.grid_cell_i >> $2)::smallint AS grid_cell_i,
									(nr.grid_cell_j >> $2)::smallint AS grid_cell_j,
									nr.label_class_id AS pred_label,
									g.gt_label,
									COUNT(*)::bigint AS delta
								FROM new_rows nr
								JOIN gt g ON g.patch_id = nr.patch_id
								GROUP BY (nr.grid_cell_i >> $2), (nr.grid_cell_j >> $2), nr.label_class_id, g.gt_label
							),
							deltas AS (
								SELECT grid_cell_i, grid_cell_j, pred_label, gt_label,
									SUM(delta) AS net_delta
								FROM (SELECT * FROM neg UNION ALL SELECT * FROM pos) t
								GROUP BY grid_cell_i, grid_cell_j, pred_label, gt_label
								HAVING SUM(delta) <> 0
							)
							INSERT INTO %s (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label, bucket_date, count)
							SELECT $1, grid_cell_i, grid_cell_j, pred_label, gt_label, CURRENT_DATE, net_delta
							FROM deltas
							ON CONFLICT (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label)
							DO UPDATE SET count = EXCLUDED.count + %s.count, bucket_date = CURRENT_DATE
							$sql$,
							v_patch_shard, v_pred_last_shard, v_cm_shard, v_cm_shard
						) USING v_patch_shardid, v_shift;

						-- Only purge non-positive rows when decrements were possible.
						EXECUTE format('DELETE FROM %s WHERE count <= 0', v_cm_shard);
					END IF;
				END LOOP;

				RETURN NULL;
			END;
			$body$;
			"""

		# Step 1b: UPDATE trigger function (patch gt_label change → all CM levels).
		# Same looping strategy — resolves all 5 CM shards and applies bit-shifted deltas.
		# Both pred_patch_latest and pred_patch_last are searched (UNION ALL duplicate-free).
		#
		# Key optimisation: SET LOCAL enable_nestloop = off at entry forces hash joins.
		# The changed CTE is MATERIALIZED so old_rows/new_rows are scanned once and reused.
		# No DDL (CREATE/DROP TEMP TABLE) — Citus blocks DDL in shard trigger functions.
		update_trigger_fn_sql = f"""
			CREATE OR REPLACE FUNCTION update_cm_on_patch_update()
			RETURNS TRIGGER LANGUAGE plpgsql AS $body$
			DECLARE
				v_pred_latest_shard   text;
				v_pred_last_shard     text;
				v_pred_last_regclass  regclass;
				v_patch_shardid       bigint;
				v_shardminvalue       text;
				v_cm_shard            text;
				v_lvl                 int;
				v_shift               int;
			BEGIN
				-- Disable nested loops for this transaction so the planner is forced to
				-- use hash joins even though it cannot estimate transition table cardinality.
				SET LOCAL enable_nestloop = off;

				v_patch_shardid := (regexp_match(TG_TABLE_NAME, '(\\d+)$'))[1]::bigint;

				SELECT shardminvalue INTO v_shardminvalue FROM pg_dist_shard WHERE shardid = v_patch_shardid;

				SELECT TG_TABLE_SCHEMA || '.' || '{pred_patch_table}_' || shardid::text
				INTO v_pred_latest_shard
				FROM pg_dist_shard
				WHERE logicalrelid = '{pred_patch_table}'::regclass
				AND shardminvalue = v_shardminvalue;

				v_pred_last_regclass := to_regclass(TG_TABLE_SCHEMA || '.pred_patch_last');
				SELECT TG_TABLE_SCHEMA || '.' || 'pred_patch_last_' || shardid::text
				INTO v_pred_last_shard
				FROM pg_dist_shard
				WHERE logicalrelid = v_pred_last_regclass
				AND shardminvalue = v_shardminvalue;

				IF v_pred_last_regclass IS NOT NULL AND v_pred_last_shard IS NULL THEN
					RAISE EXCEPTION 'could not resolve pred_patch_last shard for patch shardid %', v_patch_shardid;
				END IF;

				FOR v_lvl IN 8..12 LOOP
					v_shift := 12 - v_lvl;

					SELECT TG_TABLE_SCHEMA || '.' || 'confusion_matrix_l' || v_lvl::text || '_' || shardid::text
					INTO v_cm_shard
					FROM pg_dist_shard
					WHERE logicalrelid = ('confusion_matrix_l' || v_lvl::text)::regclass
					AND shardminvalue = v_shardminvalue;

					IF v_pred_last_shard IS NULL THEN
						-- changed is MATERIALIZED so old_rows/new_rows are scanned once.
						-- enable_nestloop=off ensures hash joins against the pred shard.
						EXECUTE format(
							$sql$
							WITH changed AS MATERIALIZED (
								SELECT o.patch_id,
									o.label_class_id AS old_gt,
									n.label_class_id AS new_gt
								FROM old_rows o
								JOIN new_rows n ON o.patch_id = n.patch_id
								WHERE o.label_class_id IS DISTINCT FROM n.label_class_id
							),
							neg AS (
								SELECT (pp.grid_cell_i >> $2)::smallint AS grid_cell_i,
									(pp.grid_cell_j >> $2)::smallint AS grid_cell_j,
									pp.label_class_id AS pred_label,
									c.old_gt AS gt_label, -COUNT(*)::bigint AS delta
								FROM changed c
								JOIN %s pp ON pp.patch_id = c.patch_id
								GROUP BY (pp.grid_cell_i >> $2), (pp.grid_cell_j >> $2), pp.label_class_id, c.old_gt
							),
							pos AS (
								SELECT (pp.grid_cell_i >> $2)::smallint AS grid_cell_i,
									(pp.grid_cell_j >> $2)::smallint AS grid_cell_j,
									pp.label_class_id AS pred_label,
									c.new_gt AS gt_label, COUNT(*)::bigint AS delta
								FROM changed c
								JOIN %s pp ON pp.patch_id = c.patch_id
								GROUP BY (pp.grid_cell_i >> $2), (pp.grid_cell_j >> $2), pp.label_class_id, c.new_gt
							),
							deltas AS (
								SELECT grid_cell_i, grid_cell_j, pred_label, gt_label,
									SUM(delta) AS net_delta
								FROM (SELECT * FROM neg UNION ALL SELECT * FROM pos) t
								GROUP BY grid_cell_i, grid_cell_j, pred_label, gt_label
								HAVING SUM(delta) <> 0
							)
							INSERT INTO %s (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label, bucket_date, count)
							SELECT $1, grid_cell_i, grid_cell_j, pred_label, gt_label, CURRENT_DATE, net_delta
							FROM deltas
							ON CONFLICT (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label)
							DO UPDATE SET count = %s.count + EXCLUDED.count, bucket_date = CURRENT_DATE
							$sql$,
							v_pred_latest_shard, v_pred_latest_shard, v_cm_shard, v_cm_shard
						) USING v_patch_shardid, v_shift;
					ELSE
						EXECUTE format(
							$sql$
							WITH changed AS MATERIALIZED (
								SELECT o.patch_id,
									o.label_class_id AS old_gt,
									n.label_class_id AS new_gt
								FROM old_rows o
								JOIN new_rows n ON o.patch_id = n.patch_id
								WHERE o.label_class_id IS DISTINCT FROM n.label_class_id
							),
							preds AS MATERIALIZED (
								SELECT patch_id, grid_cell_i, grid_cell_j, label_class_id FROM %s
								WHERE patch_id IN (SELECT patch_id FROM changed)
								UNION ALL
								SELECT patch_id, grid_cell_i, grid_cell_j, label_class_id FROM %s
								WHERE patch_id IN (SELECT patch_id FROM changed)
							),
							neg AS (
								SELECT (pp.grid_cell_i >> $2)::smallint AS grid_cell_i,
									(pp.grid_cell_j >> $2)::smallint AS grid_cell_j,
									pp.label_class_id AS pred_label,
									c.old_gt AS gt_label, -COUNT(*)::bigint AS delta
								FROM changed c
								JOIN preds pp ON pp.patch_id = c.patch_id
								GROUP BY (pp.grid_cell_i >> $2), (pp.grid_cell_j >> $2), pp.label_class_id, c.old_gt
							),
							pos AS (
								SELECT (pp.grid_cell_i >> $2)::smallint AS grid_cell_i,
									(pp.grid_cell_j >> $2)::smallint AS grid_cell_j,
									pp.label_class_id AS pred_label,
									c.new_gt AS gt_label, COUNT(*)::bigint AS delta
								FROM changed c
								JOIN preds pp ON pp.patch_id = c.patch_id
								GROUP BY (pp.grid_cell_i >> $2), (pp.grid_cell_j >> $2), pp.label_class_id, c.new_gt
							),
							deltas AS (
								SELECT grid_cell_i, grid_cell_j, pred_label, gt_label,
									SUM(delta) AS net_delta
								FROM (SELECT * FROM neg UNION ALL SELECT * FROM pos) t
								GROUP BY grid_cell_i, grid_cell_j, pred_label, gt_label
								HAVING SUM(delta) <> 0
							)
							INSERT INTO %s (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label, bucket_date, count)
							SELECT $1, grid_cell_i, grid_cell_j, pred_label, gt_label, CURRENT_DATE, net_delta
							FROM deltas
							ON CONFLICT (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label)
							DO UPDATE SET count = %s.count + EXCLUDED.count, bucket_date = CURRENT_DATE
							$sql$,
							v_pred_latest_shard, v_pred_last_shard, v_cm_shard, v_cm_shard
						) USING v_patch_shardid, v_shift;
					END IF;

					EXECUTE format('DELETE FROM %s WHERE count <= 0', v_cm_shard);
				END LOOP;

				RETURN NULL;
			END;
			$body$;
			"""

		# Step 2a: Attach AFTER INSERT trigger to each shard of both pred_patch tables.
		def _attach_insert_triggers_sql(table: str) -> str:
			return f"""
			SELECT run_command_on_shards(
				'{table}',
				$cmd$
					CREATE TRIGGER trg_update_cm AFTER INSERT ON %s
					REFERENCING NEW TABLE AS new_rows
					FOR EACH STATEMENT
					EXECUTE FUNCTION update_cm_shard()
				$cmd$
			);
			"""

		# Step 2b: Attach AFTER UPDATE trigger to each patch shard.
		attach_update_triggers_sql = """
			SELECT run_command_on_shards(
				'patch',
				$cmd$
					CREATE TRIGGER trg_update_cm_on_patch_update AFTER UPDATE ON %s
					REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
					FOR EACH STATEMENT
					EXECUTE FUNCTION update_cm_on_patch_update()
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

				cur.execute(_attach_insert_triggers_sql('pred_patch_latest'))
				print(f"Per-shard INSERT triggers installed on pred_patch_latest shards.")

				cur.execute(_attach_insert_triggers_sql('pred_patch_last'))
				print(f"Per-shard INSERT triggers installed on pred_patch_last shards.")

				cur.execute(attach_update_triggers_sql)
				print(f"Per-shard UPDATE triggers installed on {patch_table} shards.")

		print("\nAll per-shard triggers installed.")

