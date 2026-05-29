from sqlalchemy import select
from sqlalchemy.schema import CreateTable

from patchsorter.db.utils import SessionManager
from patchsorter.db.head_client.models import Base, Project, all_project_models
from patchsorter.db.head_client.patch import PatchStore
from patchsorter.db.head_client.confusion_matrix import ConfusionMatrixStore
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.config.constants import PredPatchSuffix


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
            projects = session.query(Project).all()

        for project in projects:
            all_project_models(int(project.project_id))

    def drop_all_tables(self) -> None:
        # check if the project table exists:
        with self.sm.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name = 'project';")
                if cur.fetchone() is None:
                    print("No tables found, skipping drop_all_tables.")
                    return
        self.register_project_models()
        Base.metadata.drop_all(self.sm.engine)

    def setup_schema(self) -> None:
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
            for stmt in distribution:
                try:
                    cur.execute(stmt)
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
            SELECT run_command_on_shards(
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
            SELECT run_command_on_shards(
                '{PatchStore.build_table_name(n)}',
                $cmd$
                    CREATE TRIGGER trg_update_cm_on_patch_update_p{n} AFTER UPDATE ON %s
                    REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
                    FOR EACH STATEMENT
                    EXECUTE FUNCTION update_cm_on_patch_update_p{n}()
                $cmd$
            );
            """

        with raw_conn.cursor() as cur:
            cur.execute(insert_trigger_fn_sql)
            cur.execute(f"SELECT run_command_on_workers($outer${insert_trigger_fn_sql}$outer$);")
            print(f"INSERT trigger function created on coordinator and workers for project {n}.")

            cur.execute(update_trigger_fn_sql)
            cur.execute(f"SELECT run_command_on_workers($outer${update_trigger_fn_sql}$outer$);")
            print(f"UPDATE trigger function created on coordinator and workers for project {n}.")

            cur.execute(_attach_insert_triggers_sql(PatchStore.build_pred_table_name(n, PredPatchSuffix.LATEST)))
            print(f"Per-shard INSERT triggers installed on {PatchStore.build_pred_table_name(n, PredPatchSuffix.LATEST)} shards.")

            cur.execute(_attach_insert_triggers_sql(PatchStore.build_pred_table_name(n, PredPatchSuffix.LAST)))
            print(f"Per-shard INSERT triggers installed on {PatchStore.build_pred_table_name(n, PredPatchSuffix.LAST)} shards.")

            cur.execute(attach_update_triggers_sql)
            print(f"Per-shard UPDATE triggers installed on project{n}_patch shards.")

        print(f"\nAll per-shard triggers installed for project {n}.")

    def setup_project(self, project_id: int) -> None:
        """Create per-project tables and install triggers in a single transaction.

        Calls :meth:`~patchsorter.db.head_client.project.ProjectStore.create_project_tables`
        followed by :meth:`setup_triggers` on the same raw connection so that both
        operations are committed or rolled back atomically.

        Args:
            project_id: The integer project ID to initialise.
        """

        with self.sm.get_connection() as conn:
            self.create_project_tables(project_id, conn)
            self.setup_triggers(project_id, conn)
            conn.commit()