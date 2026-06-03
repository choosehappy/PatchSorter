from sqlalchemy import select, text
from sqlalchemy.schema import CreateTable

from patchsorter.db.utils import SessionManager
from patchsorter.db.head_client.models import Base, Project, all_project_models
from patchsorter.db.head_client.patch import PatchStore
from patchsorter.db.head_client.confusion_matrix import ConfusionMatrixStore
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.config.constants import PredPatchSuffix
# Clear per-project model caches so they are not in Base.metadata
# when create_all() runs.  Project tables must only be created by
# setup_project().
from patchsorter.db.head_client.models import (
    _cm_cache,
    _patch_cache,
    _pred_patch_last_cache,
    _pred_patch_latest_cache,
)

from typing import Any, Dict, List


class DatabaseManager:
    """Schema and DDL manager implemented on top of a SessionManager."""

    def __init__(self, session_manager: SessionManager):
        self.sm = session_manager

    def get_worker_nodes(self) -> List[Dict[str, Any]]:
        from psycopg.rows import dict_row

        with self.sm.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM citus_get_active_worker_nodes();")
                return cur.fetchall()

    def register_project_models(self) -> None:
        """Query all existing project IDs and register their per-project ORM
        models with ``Base.metadata``.

        Call this once at application startup so that operations such as
        ``drop_all_tables`` and ``setup_schema`` are aware of all project-
        scoped tables (``project{N}_patch``, ``project{N}_pred_patch_*``,
        ``project{N}_confusion_matrix_l*``) and can resolve FK dependencies
        correctly without manual CASCADE workarounds.
        """
        with self.sm.get_session() as session:
            project_ids = session.execute(select(Project.project_id)).scalars().all()

        for project_id in project_ids:
            all_project_models(int(project_id))

    def drop_all_tables(self) -> None:
        # check if the project table exists:
        with self.sm.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'project';")
                if cur.fetchone() is None:
                    print("No tables found, skipping drop_all_tables.")
                    return
        # Drop base tables via ORM.
        Base.metadata.drop_all(self.sm.engine)
        # Drop per-project tables (project{N}_*) via raw SQL.
        with self.sm.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name LIKE 'project%_%%';"
                )
                for (schema, tbl) in cur.fetchall():
                    cur.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")
                    print(f"Dropped {schema}.{tbl}")

    def setup_schema(self) -> None:
        """Create all tables and extensions required by the application.
        """

        for key in list(_patch_cache):
            del Base.metadata.tables[PatchStore.build_table_name(key)]
        _patch_cache.clear()
        for key in list(_pred_patch_latest_cache):
            del Base.metadata.tables[PatchStore.build_pred_table_name(key, PredPatchSuffix.LATEST)]
            del Base.metadata.tables[PatchStore.build_pred_table_name(key, PredPatchSuffix.LAST)]
        _pred_patch_latest_cache.clear()
        _pred_patch_last_cache.clear()
        for (pid, lvl) in list(_cm_cache):
            del Base.metadata.tables[ConfusionMatrixStore.build_table_name(pid, lvl)]
        _cm_cache.clear()

        Base.metadata.create_all(self.sm.engine)

        # Seed the reserved "unassigned" label class (label_class_id = 1)
        seed_statement = """
            INSERT INTO label_class (project_id, name, color_code)
            SELECT NULL, 'unassigned', NULL
            WHERE NOT EXISTS (SELECT 1 FROM label_class WHERE label_class_id = 1);
        """
        distribution_statements = [
            "SELECT create_reference_table('project');",
            "SELECT create_reference_table('image');",
            "SELECT create_reference_table('label_class');",
            "SELECT create_reference_table('settings');",
            "SELECT create_reference_table('log');",
        ]
        with self.sm.get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    # Citus propagates extensions to workers automatically.
                    cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
                except Exception as e:
                    print(f"PostGIS extension creation failed: {e}")

                try:
                    cur.execute("CREATE EXTENSION IF NOT EXISTS citus;")
                except Exception as e:
                    print(f"Citus extension creation failed: {e}")

                cur.execute(seed_statement)
                for stmt in distribution_statements:
                    try:
                        cur.execute(stmt)
                    except Exception as e:
                        print(f"Distribution command failed (may already be distributed): {e}")
                

            conn.commit()

        with self.sm.get_session() as session:
            SettingsStore(session).seed_app_settings()

    def rotate_pred_patch_tables(self, project_id: int) -> None:
        """Rotate ``pred_patch_latest`` → ``pred_patch_last`` via a 3-way rename.

        No rows are copied and no tables are created or dropped.  Triggers
        travel with their physical shard objects and do not need to be
        re-registered after the rename.

        The rotation proceeds in four atomic steps:

        1. ``TRUNCATE project{N}_pred_patch_last`` — free stale data from the
           previous epoch.
        2. ``RENAME project{N}_pred_patch_last → project{N}_pred_patch_tmp``
        3. ``RENAME project{N}_pred_patch_latest → project{N}_pred_patch_last``
        4. ``RENAME project{N}_pred_patch_tmp → project{N}_pred_patch_latest``
        """
        n = project_id
        last_table   = PatchStore.build_pred_table_name(n, PredPatchSuffix.LAST)
        latest_table = PatchStore.build_pred_table_name(n, PredPatchSuffix.LATEST)
        tmp_table    = f"project{n}_pred_patch_tmp"
        with self.sm.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE TABLE {last_table};")
                cur.execute(f"ALTER TABLE {last_table} RENAME TO {tmp_table};")
                cur.execute(f"ALTER TABLE {latest_table} RENAME TO {last_table};")
                cur.execute(f"ALTER TABLE {tmp_table} RENAME TO {latest_table};")
            conn.commit()

    def create_project_tables(self, project_id: int, conn) -> None:
        """Create and distribute the per-project tables for *project_id*.

        Creates (idempotent — ``checkfirst=True``):

        - ``project{N}_patch`` — distributed by ``patch_id``.
        - ``project{N}_pred_patch_latest`` — co-located with patch.
        - ``project{N}_pred_patch_last`` — co-located with patch.
        - ``project{N}_confusion_matrix_l8`` … ``project{N}_confusion_matrix_l12``
          — each distributed by ``shard_id``, co-located with patch.

        Args:
            project_id: The integer project ID.  Used as the ``{N}`` suffix in
                all table names.
            conn: A raw psycopg connection.  The caller is responsible for
                committing.
        """
        n = project_id
        models = all_project_models(n)

        patch_tbl = PatchStore.build_table_name(n)
        distribution = [
            f"SELECT create_distributed_table('{patch_tbl}', 'patch_id');",
            f"SELECT create_distributed_table('{PatchStore.build_pred_table_name(n, PredPatchSuffix.LATEST)}', 'patch_id', colocate_with => '{patch_tbl}');",
            f"SELECT create_distributed_table('{PatchStore.build_pred_table_name(n, PredPatchSuffix.LAST)}', 'patch_id', colocate_with => '{patch_tbl}');",
            *[
                f"SELECT create_distributed_table('{ConfusionMatrixStore.build_table_name(n, lvl)}', 'shard_id', colocate_with => '{patch_tbl}');"
                for lvl in range(8, 13)
            ],
        ]
        with conn.cursor() as cur:
            for model in models:
                ddl = str(CreateTable(model.__table__, if_not_exists=True).compile(self.sm.engine))
                cur.execute(ddl)
                print(f"Ensured existence of table {model.__tablename__} for project {n}.")
            for stmt in distribution:
                try:
                    cur.execute(stmt)
                    print(f"Executed distribution command for project {n}: {stmt}")
                except Exception as exc:
                    print(f"Distribution command failed (may already be distributed): {exc}")

    def setup_triggers(self, project_id: int, raw_conn) -> None:
        """Install per-shard statement-level triggers for hierarchical confusion matrix maintenance.

        Five CM tables (project{N}_confusion_matrix_l8 through l12) are maintained in
        lock-step.  l12 stores raw (finest-level) grid cell counts; each coarser level
        right-shifts grid_cell_i/j by one additional bit relative to l12.

        Trigger A (AFTER INSERT on project{N}_pred_patch shards): joins new prediction rows
        with the colocated patch shard to obtain gt_label, then upserts aggregated counts
        into all five colocated CM shards in a single loop.

        Trigger B (AFTER UPDATE on project{N}_patch shards): detects gt_label changes,
        computes net deltas against the colocated pred_patch shard, upserts into all five
        CM shards, and removes rows whose count reaches zero or below.

        Both trigger functions resolve their target CM shards dynamically from pg_dist_shard
        using the shardminvalue of the firing shard — no TG_ARGV required.

        Args:
            project_id: The integer project ID.  Used as the ``{N}`` suffix in all
                project-scoped table and function names.
            raw_conn: A raw psycopg connection.  The caller is responsible for
                committing.  Trigger DDL is transactional in Citus.
        """
        n = project_id

        # INSERT trigger function (pred_patch → all CM levels).
        # pred_patch_last always exists (created by create_project_tables) so no NULL
        # guard is needed — an empty last table simply contributes 0 neg rows.
        # SET LOCAL enable_nestloop = off forces hash joins against transition tables.
        insert_trigger_fn_sql = f"""
            CREATE OR REPLACE FUNCTION update_cm_shard_p{n}()
            RETURNS TRIGGER LANGUAGE plpgsql AS $body$
            DECLARE
                v_patch_shard   text;
                v_pred_last_shard text;
                v_pred_shardid  bigint;
                v_patch_shardid bigint;
                v_shardminvalue text;
                v_cm_shard      text;
                v_lvl           int;
                v_shift         int;
            BEGIN
                SET LOCAL enable_nestloop = off;

                v_pred_shardid := (regexp_match(TG_TABLE_NAME, '(\\d+)$'))[1]::bigint;
                SELECT shardminvalue INTO v_shardminvalue FROM pg_dist_shard WHERE shardid = v_pred_shardid;

                SELECT TG_TABLE_SCHEMA || '.' || '{PatchStore.build_table_name(n)}_' || shardid::text
                INTO v_patch_shard FROM pg_dist_shard
                WHERE logicalrelid = '{PatchStore.build_table_name(n)}'::regclass AND shardminvalue = v_shardminvalue;

                v_patch_shardid := (regexp_match(v_patch_shard, '(\\d+)$'))[1]::bigint;

                SELECT TG_TABLE_SCHEMA || '.' || '{PatchStore.build_pred_table_name(n, PredPatchSuffix.LAST)}_' || shardid::text
                INTO v_pred_last_shard FROM pg_dist_shard
                WHERE logicalrelid = '{PatchStore.build_pred_table_name(n, PredPatchSuffix.LAST)}'::regclass AND shardminvalue = v_shardminvalue;

                FOR v_lvl IN 8..12 LOOP
                    v_shift := 12 - v_lvl;

                    SELECT TG_TABLE_SCHEMA || '.' || '{ConfusionMatrixStore.build_table_name(n)}' || v_lvl::text || '_' || shardid::text
                    INTO v_cm_shard FROM pg_dist_shard
                    WHERE logicalrelid = ('{ConfusionMatrixStore.build_table_name(n)}' || v_lvl::text)::regclass AND shardminvalue = v_shardminvalue;

                    EXECUTE format(
                        $sql$
                        WITH
                        gt AS MATERIALIZED (
                            SELECT nr.patch_id, p.label_class_id AS gt_label
                            FROM new_rows nr JOIN %s p ON p.patch_id = nr.patch_id
                        ),
                        neg AS (
                            SELECT (pl.grid_cell_i >> $2)::smallint AS grid_cell_i,
                                (pl.grid_cell_j >> $2)::smallint AS grid_cell_j,
                                pl.label_class_id AS pred_label, g.gt_label,
                                -COUNT(*)::bigint AS delta
                            FROM new_rows nr
                            JOIN %s pl ON pl.patch_id = nr.patch_id
                            JOIN gt g ON g.patch_id = nr.patch_id
                            GROUP BY (pl.grid_cell_i >> $2), (pl.grid_cell_j >> $2), pl.label_class_id, g.gt_label
                        ),
                        pos AS (
                            SELECT (nr.grid_cell_i >> $2)::smallint AS grid_cell_i,
                                (nr.grid_cell_j >> $2)::smallint AS grid_cell_j,
                                nr.label_class_id AS pred_label, g.gt_label,
                                COUNT(*)::bigint AS delta
                            FROM new_rows nr JOIN gt g ON g.patch_id = nr.patch_id
                            GROUP BY (nr.grid_cell_i >> $2), (nr.grid_cell_j >> $2), nr.label_class_id, g.gt_label
                        ),
                        deltas AS (
                            SELECT grid_cell_i, grid_cell_j, pred_label, gt_label, SUM(delta) AS net_delta
                            FROM (SELECT * FROM neg UNION ALL SELECT * FROM pos) t
                            GROUP BY grid_cell_i, grid_cell_j, pred_label, gt_label
                            HAVING SUM(delta) <> 0
                        )
                        INSERT INTO %s (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label, bucket_date, count)
                        SELECT $1, grid_cell_i, grid_cell_j, pred_label, gt_label, CURRENT_DATE, net_delta FROM deltas
                        ON CONFLICT (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label)
                        DO UPDATE SET count = EXCLUDED.count + %s.count, bucket_date = CURRENT_DATE
                        $sql$,
                        v_patch_shard, v_pred_last_shard, v_cm_shard, v_cm_shard
                    ) USING v_patch_shardid, v_shift;

                    EXECUTE format('DELETE FROM %s WHERE count <= 0', v_cm_shard);
                END LOOP;

                RETURN NULL;
            END;
            $body$;
            """

        # UPDATE trigger function (patch gt_label change → all CM levels).
        # Unions pred_patch_latest and pred_patch_last for complete prediction coverage.
        # SET LOCAL enable_nestloop = off forces hash joins against transition tables.
        update_trigger_fn_sql = f"""
            CREATE OR REPLACE FUNCTION update_cm_on_patch_update_p{n}()
            RETURNS TRIGGER LANGUAGE plpgsql AS $body$
            DECLARE
                v_pred_latest_shard text;
                v_pred_last_shard   text;
                v_patch_shardid     bigint;
                v_shardminvalue     text;
                v_cm_shard          text;
                v_lvl               int;
                v_shift             int;
            BEGIN
                SET LOCAL enable_nestloop = off;

                v_patch_shardid := (regexp_match(TG_TABLE_NAME, '(\\d+)$'))[1]::bigint;
                SELECT shardminvalue INTO v_shardminvalue FROM pg_dist_shard WHERE shardid = v_patch_shardid;

                SELECT TG_TABLE_SCHEMA || '.' || '{PatchStore.build_pred_table_name(n, PredPatchSuffix.LATEST)}_' || shardid::text
                INTO v_pred_latest_shard FROM pg_dist_shard
                WHERE logicalrelid = '{PatchStore.build_pred_table_name(n, PredPatchSuffix.LATEST)}'::regclass AND shardminvalue = v_shardminvalue;

                SELECT TG_TABLE_SCHEMA || '.' || '{PatchStore.build_pred_table_name(n, PredPatchSuffix.LAST)}_' || shardid::text
                INTO v_pred_last_shard FROM pg_dist_shard
                WHERE logicalrelid = '{PatchStore.build_pred_table_name(n, PredPatchSuffix.LAST)}'::regclass AND shardminvalue = v_shardminvalue;

                FOR v_lvl IN 8..12 LOOP
                    v_shift := 12 - v_lvl;

                    SELECT TG_TABLE_SCHEMA || '.' || '{ConfusionMatrixStore.build_table_name(n)}' || v_lvl::text || '_' || shardid::text
                    INTO v_cm_shard FROM pg_dist_shard
                    WHERE logicalrelid = ('{ConfusionMatrixStore.build_table_name(n)}' || v_lvl::text)::regclass AND shardminvalue = v_shardminvalue;

                    EXECUTE format(
                        $sql$
                        WITH
                        changed AS MATERIALIZED (
                            SELECT o.patch_id, o.label_class_id AS old_gt, n.label_class_id AS new_gt
                            FROM old_rows o JOIN new_rows n ON o.patch_id = n.patch_id
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
                                pp.label_class_id AS pred_label, c.old_gt AS gt_label,
                                -COUNT(*)::bigint AS delta
                            FROM changed c JOIN preds pp ON pp.patch_id = c.patch_id
                            GROUP BY (pp.grid_cell_i >> $2), (pp.grid_cell_j >> $2), pp.label_class_id, c.old_gt
                        ),
                        pos AS (
                            SELECT (pp.grid_cell_i >> $2)::smallint AS grid_cell_i,
                                (pp.grid_cell_j >> $2)::smallint AS grid_cell_j,
                                pp.label_class_id AS pred_label, c.new_gt AS gt_label,
                                COUNT(*)::bigint AS delta
                            FROM changed c JOIN preds pp ON pp.patch_id = c.patch_id
                            GROUP BY (pp.grid_cell_i >> $2), (pp.grid_cell_j >> $2), pp.label_class_id, c.new_gt
                        ),
                        deltas AS (
                            SELECT grid_cell_i, grid_cell_j, pred_label, gt_label, SUM(delta) AS net_delta
                            FROM (SELECT * FROM neg UNION ALL SELECT * FROM pos) t
                            GROUP BY grid_cell_i, grid_cell_j, pred_label, gt_label
                            HAVING SUM(delta) <> 0
                        )
                        INSERT INTO %s (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label, bucket_date, count)
                        SELECT $1, grid_cell_i, grid_cell_j, pred_label, gt_label, CURRENT_DATE, net_delta FROM deltas
                        ON CONFLICT (shard_id, grid_cell_i, grid_cell_j, pred_label, gt_label)
                        DO UPDATE SET count = %s.count + EXCLUDED.count, bucket_date = CURRENT_DATE
                        $sql$,
                        v_pred_latest_shard, v_pred_last_shard, v_cm_shard, v_cm_shard
                    ) USING v_patch_shardid, v_shift;

                    EXECUTE format('DELETE FROM %s WHERE count <= 0', v_cm_shard);
                END LOOP;

                RETURN NULL;
            END;
            $body$;
            """

        # Step 2a: Attach AFTER INSERT trigger to each shard of both pred_patch tables.
        # Triggers are pre-attached to both pred_patch_latest AND pred_patch_last so
        # that after a RENAME-based rotation the trigger survives on whichever physical
        # shard set ends up named pred_patch_latest.
        # No TG_ARGV needed — CM shards are resolved dynamically inside the function.
        def _attach_insert_triggers_sql(table: str) -> str:
            return f"""
            SELECT * FROM run_command_on_shards(
                '{table}',
                $cmd$
                    CREATE TRIGGER trg_update_cm_p{n} AFTER INSERT ON %s
                    REFERENCING NEW TABLE AS new_rows
                    FOR EACH STATEMENT
                    EXECUTE FUNCTION update_cm_shard_p{n}()
                $cmd$
            );
            """

        # Step 2b: Attach AFTER UPDATE trigger to each project{N}_patch shard.
        attach_update_triggers_sql = f"""
            SELECT * FROM run_command_on_shards(
                '{PatchStore.build_table_name(n)}',
                $cmd$
                    CREATE TRIGGER trg_update_cm_on_patch_update_p{n} AFTER UPDATE ON %s
                    REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
                    FOR EACH STATEMENT
                    EXECUTE FUNCTION update_cm_on_patch_update_p{n}()
                $cmd$
            );
            """

        def _run_and_check_workers(cur, sql: str, label: str) -> None:
            cur.execute(f"SELECT * FROM run_command_on_workers($outer${sql}$outer$);")
            rows = cur.fetchall()
            failures = [r for r in rows if not r[2]]
            if failures:
                for r in failures:
                    print(f"  FAILED on worker {r[0]}:{r[1]}: {r[3]}")
                raise RuntimeError(f"{label} failed on {len(failures)} worker(s)")
            print(f"{label} succeeded on {len(rows)} worker(s).")

        def _run_and_check_shards(cur, sql: str, label: str) -> None:
            cur.execute(sql)
            rows = cur.fetchall()
            failures = [r for r in rows if not r[1]]
            if failures:
                for r in failures:
                    print(f"  FAILED on shard {r[0]}: {r[2]}")
                raise RuntimeError(f"{label} failed on {len(failures)} shard(s)")
            print(f"{label} succeeded on {len(rows)} shard(s).")

        # Phase 1: create trigger functions on coordinator (and workers).
        # Must commit before Phase 2 so run_command_on_shards (which opens a
        # fresh connection) can see the functions.
        with raw_conn.cursor() as cur:
            cur.execute(insert_trigger_fn_sql)
            _run_and_check_workers(cur, insert_trigger_fn_sql, f"INSERT trigger function (project {n}) on workers")

            cur.execute(update_trigger_fn_sql)
            _run_and_check_workers(cur, update_trigger_fn_sql, f"UPDATE trigger function (project {n}) on workers")

        raw_conn.commit()
        print(f"Trigger functions committed for project {n}.")

        # Phase 2: attach triggers to shards via run_command_on_shards.
        with raw_conn.cursor() as cur:
            _run_and_check_shards(
                cur,
                _attach_insert_triggers_sql(PatchStore.build_pred_table_name(n, PredPatchSuffix.LATEST)),
                f"Per-shard INSERT triggers on {PatchStore.build_pred_table_name(n, PredPatchSuffix.LATEST)}",
            )

            _run_and_check_shards(
                cur,
                _attach_insert_triggers_sql(PatchStore.build_pred_table_name(n, PredPatchSuffix.LAST)),
                f"Per-shard INSERT triggers on {PatchStore.build_pred_table_name(n, PredPatchSuffix.LAST)}",
            )

            _run_and_check_shards(
                cur,
                attach_update_triggers_sql,
                f"Per-shard UPDATE triggers on project{n}_patch",
            )

        print(f"\nAll per-shard triggers installed for project {n}.")

    def setup_project(self, project_id: int) -> None:
        """Create per-project tables and install triggers in a single transaction.

        Calls :meth:`~patchsorter.db.head_client.project.ProjectStore.create_project_tables`
        followed by :meth:`setup_triggers` on the same raw connection so that both
        operations are committed or rolled back atomically.

        Args:
            project_id: The integer project ID to initialise.
        """

        # Use a single raw connection for both DDL and trigger installation
        # so the operations are committed or rolled back atomically.  Also
        # ensure Citus runs these multi-shard function commands sequentially
        # rather than in parallel — set this at the start of the transaction
        # so the mode applies before any distributed operations occur.
        with self.sm.get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("SET citus.multi_shard_modify_mode TO 'sequential';")
                except Exception:
                    pass

            self.create_project_tables(project_id, conn)
            # Commit table creation so shard tables and distribution metadata
            # are visible to run_command_on_shards (which opens new connections).
            conn.commit()

            self.setup_triggers(project_id, conn)
            conn.commit()

    def get_shard_map_for_patch_and_pred(self, project_id: int) -> CitusShardMap:
        """Get a mapping of {patch_shard_id: pred_patch_shard_id} for the colocated shards of project{N}_patch and project{N}_pred_patch_latest.

        This is used by the application to route queries to the correct shard when joining patch and pred_patch tables together.
        """
        with self.sm.get_session() as session:
            return CitusShardMap(session, PatchStore.build_table_name(project_id), PatchStore.build_pred_table_name(project_id, PredPatchSuffix.LATEST))
            
    def clear_predictions(self, project_id: int) -> None:
        """Clear all rows from all pred_patch tables across all projects.

        This is used to free up space after a training epoch completes and the
        latest predictions have been rotated to the last table.  It is safe to
        call this method at any time — it will simply truncate all pred_patch
        tables, which may be empty if no epochs have completed yet.

        """
        with self.sm.get_session() as session:
            patch_store = PatchStore(project_id, session)
            patch_store.clear_predictions()

            for level in range(8, 13):
                cm_store = ConfusionMatrixStore(project_id, level, session)
                cm_store.clear_confusion_matrix()


class CitusShardMap:
    def __init__(self, session, table_a: str, table_b: str):
        self.table_a = table_a
        self.table_b = table_b

        self.map = self._get_map_for_tables(session,table_a, table_b)

    @staticmethod
    def _get_map_for_tables(session, table_a: str, table_b: str):
        """
        Returns a dictionary mapping {shard_id_a: shard_id_b} 
        for two colocated tables.
        """
        query = text(f"""
            SELECT s1.shardid AS shard_a, s2.shardid AS shard_b
            FROM pg_dist_shard s1
            JOIN pg_dist_shard s2 ON s1.shardminvalue = s2.shardminvalue 
                                 AND s1.shardmaxvalue = s2.shardmaxvalue
            JOIN pg_dist_partition p1 ON s1.logicalrelid = p1.logicalrelid
            JOIN pg_dist_partition p2 ON s2.logicalrelid = p2.logicalrelid
            WHERE s1.logicalrelid = '{table_a}'::regclass
              AND s2.logicalrelid = '{table_b}'::regclass
              AND p1.colocationid = p2.colocationid;
        """)
        result = session.execute(query)
        rows = result.fetchall()
        return {row.shard_a: row.shard_b for row in rows}
        
    def get_table_a_shard_list(self) -> List[int]:
        return list(self.map.keys())
    
    def get_table_b_shard_list(self) -> List[int]:
        return list(self.map.values())
    
    def get_b_shard_for_a_shard(self, shard_a: int) -> int:
        return self.map[shard_a]