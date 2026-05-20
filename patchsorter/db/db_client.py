
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import URL
from typing import Any, Dict, List

from patchsorter.db.constants import (
    CITUS_HEAD_HOST,
    CITUS_HEAD_PORT,
    CITUS_HEAD_DB,
    CITUS_HEAD_USER,
    CITUS_HEAD_PASSWORD,
    CITUS_WORKER_HOST,
    CITUS_WORKER_PORT,
    CITUS_WORKER_DB,
    CITUS_WORKER_USER,
    CITUS_WORKER_PASSWORD,
)


class CitusHeadClient:
    """Connection factory and DDL manager for the Citus coordinator node.

    Manages a SQLAlchemy engine with connection pooling and exposes both an
    ORM ``session_factory`` (for normal queries via stores) and a raw psycopg
    ``get_connection()`` (for DDL and Citus shard operations that cannot run
    inside a regular transaction or need ``run_command_on_workers``).

    Attributes:
        engine: The SQLAlchemy engine bound to the coordinator.
        session_factory: A ``sessionmaker`` bound to ``engine``.
    """

    def __init__(
        self,
        host: str = CITUS_HEAD_HOST,
        port: int = CITUS_HEAD_PORT,
        dbname: str = CITUS_HEAD_DB,
        user: str = CITUS_HEAD_USER,
        password: str = CITUS_HEAD_PASSWORD,
    ) -> None:
        """Initialise the coordinator client.

        Args:
            host: Hostname or IP address of the Citus coordinator.
            port: PostgreSQL port on the coordinator.
            dbname: Database name.
            user: PostgreSQL user.
            password: PostgreSQL password.
        """
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
        self.session_factory = sessionmaker(bind=self.engine)

    def get_connection(self):
        """Return a raw psycopg connection from the engine pool.

        Use this for DDL statements (``CREATE TABLE``, ``ALTER TABLE``,
        ``DROP TABLE``) and Citus-specific functions such as
        ``run_command_on_workers`` and ``run_command_on_shards`` that are not
        supported inside a SQLAlchemy ORM session.

        Returns:
            A raw psycopg connection.  Callers are responsible for committing
            or rolling back and for returning the connection to the pool by
            calling ``close()``.
        """
        return self.engine.raw_connection()

    def get_worker_nodes(self) -> List[Dict[str, Any]]:
        """List all active Citus worker nodes.

        Returns:
            A list of dicts with worker-node metadata as returned by
            ``citus_get_active_worker_nodes()``.
        """
        from psycopg.rows import dict_row
        with self.get_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT * FROM citus_get_active_worker_nodes();")
                return cur.fetchall()

    def drop_all_tables(self) -> None:
        """Drop all shared reference tables in reverse dependency order.

        Drops ``settings``, ``log``, ``label_class``, ``image``, and
        ``project``.  Per-project distributed tables (``project{N}_patch``,
        ``project{N}_pred_patch_*``, ``project{N}_confusion_matrix_l*``) must
        be dropped separately via
        :meth:`~patchsorter.db.stores.project.ProjectStore.delete`.
        """
        statements = [
            "DROP TABLE IF EXISTS settings CASCADE;",
            "DROP TABLE IF EXISTS log CASCADE;",
            "DROP TABLE IF EXISTS label_class CASCADE;",
            "DROP TABLE IF EXISTS image CASCADE;",
            "DROP TABLE IF EXISTS project CASCADE;",
        ]
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)
            conn.commit()

    def setup_schema(self) -> None:
        """Create all shared reference tables and configure Citus distribution.

        Creates the following tables (idempotent — uses ``IF NOT EXISTS``):

        - ``project`` — one row per project, with a UUID external identifier.
        - ``image`` — one row per whole-slide image.
        - ``label_class`` — annotation classes per project.
        - ``settings`` — key/value configuration at application or project level.
        - ``log`` — application-level event log.

        All tables are registered as Citus *reference tables* so that they are
        replicated to every worker and can be joined with distributed tables
        without network round-trips.

        Per-project distributed tables (``project{N}_patch``,
        ``project{N}_pred_patch_latest``, ``project{N}_pred_patch_last``, and
        five confusion-matrix levels) are created on demand via
        :meth:`~patchsorter.db.stores.project.ProjectStore.create_project_tables`.

        Note:
            Citus distribution commands are attempted after table creation.
            Failures (e.g. table already distributed) are printed but not
            re-raised.
        """
        schema_statements = [
            """CREATE TABLE IF NOT EXISTS project (
                project_id   SERIAL    PRIMARY KEY,
                project_uid  UUID      NOT NULL UNIQUE DEFAULT gen_random_uuid(),
                project_name TEXT      NOT NULL,
                description  TEXT
            );""",
            """CREATE TABLE IF NOT EXISTS image (
                image_id          SERIAL    PRIMARY KEY,
                image_uid         UUID      NOT NULL UNIQUE DEFAULT gen_random_uuid(),
                project_id        INT       NOT NULL REFERENCES project(project_id),
                name              TEXT      NOT NULL,
                image_path        TEXT      NOT NULL,
                upload_ts         TIMESTAMP NOT NULL,
                base_mag          FLOAT     NOT NULL,
                base_width        INT       NOT NULL,
                base_height       INT       NOT NULL,
                deepzoom_tilesize INT       NOT NULL,
                embedding_x       FLOAT,
                embedding_y       FLOAT,
                group_id          INT,
                train_test_split  INT,
                UNIQUE(project_id, name)
            );""",
            """CREATE TABLE IF NOT EXISTS label_class (
                label_class_id  SERIAL    PRIMARY KEY,
                label_class_uid UUID      NOT NULL UNIQUE DEFAULT gen_random_uuid(),
                project_id      INT       NOT NULL REFERENCES project(project_id),
                name            TEXT      NOT NULL,
                color_code      TEXT,
                event_ts        TIMESTAMP NOT NULL,
                UNIQUE(project_id, name)
            );""",
            """CREATE TABLE IF NOT EXISTS settings (
                setting_id    SERIAL  PRIMARY KEY,
                setting_uid   UUID    NOT NULL UNIQUE DEFAULT gen_random_uuid(),
                project_id    INT     REFERENCES project(project_id),
                setting_key   TEXT    NOT NULL,
                setting_value TEXT    NOT NULL,
                disabled      BOOLEAN NOT NULL DEFAULT FALSE
            );""",
            """CREATE TABLE IF NOT EXISTS log (
                id        SERIAL    PRIMARY KEY,
                name      TEXT      NOT NULL,
                timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
                level     TEXT      NOT NULL DEFAULT 'INFO',
                message   TEXT      NOT NULL DEFAULT ''
            );""",
        ]
        distribution_statements = [
            "SELECT create_reference_table('project');",
            "SELECT create_reference_table('image');",
            "SELECT create_reference_table('label_class');",
            "SELECT create_reference_table('settings');",
            "SELECT create_reference_table('log');",
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
            conn.commit()

    def setup_triggers(self, project_id: int) -> None:
        """Install per-shard triggers for hierarchical confusion-matrix maintenance.

        Creates two PL/pgSQL trigger functions scoped to *project_id* and
        attaches them as statement-level ``AFTER`` triggers to every Citus
        shard of the project's patch and pred-patch tables:

        - ``update_cm_shard_p{N}`` — fired ``AFTER INSERT`` on each
          ``project{N}_pred_patch_latest`` and ``project{N}_pred_patch_last``
          shard.  Joins incoming prediction rows with the co-located patch
          shard to obtain the ground-truth label, then upserts aggregated
          counts into all five co-located confusion-matrix shards (levels
          l8–l12).
        - ``update_cm_on_patch_update_p{N}`` — fired ``AFTER UPDATE`` on each
          ``project{N}_patch`` shard.  Detects ``label_class_id`` changes,
          computes net count deltas against all co-located pred-patch shards,
          upserts into the five CM shards, and purges rows whose count falls
          to zero or below.

        Both functions resolve target CM shards dynamically from
        ``pg_dist_shard`` using the ``shardminvalue`` of the firing shard, so
        no shard IDs need to be passed as trigger arguments.

        The functions are installed on the coordinator **and** propagated to
        every worker via ``run_command_on_workers``.

        Args:
            project_id: Integer ID of the project whose tables receive
                triggers.  Determines the project-scoped table names and
                uniquely names the trigger functions to avoid conflicts
                between projects.
        """
        n = project_id
        patch_table = f"project{n}_patch"
        pred_patch_table = f"project{n}_pred_patch_latest"
        pred_patch_last_table = f"project{n}_pred_patch_last"
        cm_prefix = f"project{n}_confusion_matrix_l"
        insert_fn_name = f"update_cm_shard_p{n}"
        update_fn_name = f"update_cm_on_patch_update_p{n}"

        # ------------------------------------------------------------------ #
        # Step 1a: INSERT trigger function (pred_patch → all CM levels).      #
        # Loops over l8..l12 inside the trigger body.  For each level the     #
        # co-located CM shard is resolved dynamically from pg_dist_shard      #
        # using v_shardminvalue.  The bit-shift (12 - level) maps l12         #
        # grid_cell_i/j down to coarser levels.                               #
        #                                                                      #
        # Key optimisation: SET LOCAL enable_nestloop = off at entry forces   #
        # the planner to use hash joins for all joins in this trigger          #
        # invocation.  This prevents catastrophic nested-loop plans that      #
        # arise because the planner cannot estimate the cardinality of         #
        # transition table (new_rows) references inside EXECUTE blocks.       #
        # No DDL (CREATE/DROP TEMP TABLE) is used — Citus blocks DDL in shard #
        # triggers.                                                            #
        # ------------------------------------------------------------------ #
        insert_trigger_fn_sql = f"""
            CREATE OR REPLACE FUNCTION {insert_fn_name}()
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
                SET LOCAL enable_nestloop = off;

                v_pred_shardid := (regexp_match(TG_TABLE_NAME, '(\\d+)$'))[1]::bigint;

                SELECT shardminvalue INTO v_shardminvalue FROM pg_dist_shard WHERE shardid = v_pred_shardid;

                SELECT TG_TABLE_SCHEMA || '.' || '{patch_table}_' || shardid::text
                INTO v_patch_shard
                FROM pg_dist_shard
                WHERE logicalrelid = '{patch_table}'::regclass
                AND shardminvalue = v_shardminvalue;

                v_patch_shardid := (regexp_match(v_patch_shard, '(\\d+)$'))[1]::bigint;

                v_pred_last_regclass := to_regclass(TG_TABLE_SCHEMA || '.{pred_patch_last_table}');
                SELECT TG_TABLE_SCHEMA || '.' || '{pred_patch_last_table}_' || shardid::text
                INTO v_pred_last_shard
                FROM pg_dist_shard
                WHERE logicalrelid = v_pred_last_regclass
                AND shardminvalue = v_shardminvalue;

                IF v_pred_last_regclass IS NOT NULL AND v_pred_last_shard IS NULL THEN
                    RAISE EXCEPTION 'could not resolve {pred_patch_last_table} shard for pred shardid %', v_pred_shardid;
                END IF;

                FOR v_lvl IN 8..12 LOOP
                    v_shift := 12 - v_lvl;

                    SELECT TG_TABLE_SCHEMA || '.' || '{cm_prefix}' || v_lvl::text || '_' || shardid::text
                    INTO v_cm_shard
                    FROM pg_dist_shard
                    WHERE logicalrelid = ('{cm_prefix}' || v_lvl::text)::regclass
                    AND shardminvalue = v_shardminvalue;

                    IF v_pred_last_shard IS NULL THEN
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

                        EXECUTE format('DELETE FROM %s WHERE count <= 0', v_cm_shard);
                    END IF;
                END LOOP;

                RETURN NULL;
            END;
            $body$;
            """

        # ------------------------------------------------------------------ #
        # Step 1b: UPDATE trigger function (patch gt_label change → all CM   #
        # levels).  The changed CTE is MATERIALIZED so old_rows/new_rows are  #
        # scanned once and reused.                                             #
        # ------------------------------------------------------------------ #
        update_trigger_fn_sql = f"""
            CREATE OR REPLACE FUNCTION {update_fn_name}()
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
                SET LOCAL enable_nestloop = off;

                v_patch_shardid := (regexp_match(TG_TABLE_NAME, '(\\d+)$'))[1]::bigint;

                SELECT shardminvalue INTO v_shardminvalue FROM pg_dist_shard WHERE shardid = v_patch_shardid;

                SELECT TG_TABLE_SCHEMA || '.' || '{pred_patch_table}_' || shardid::text
                INTO v_pred_latest_shard
                FROM pg_dist_shard
                WHERE logicalrelid = '{pred_patch_table}'::regclass
                AND shardminvalue = v_shardminvalue;

                v_pred_last_regclass := to_regclass(TG_TABLE_SCHEMA || '.{pred_patch_last_table}');
                SELECT TG_TABLE_SCHEMA || '.' || '{pred_patch_last_table}_' || shardid::text
                INTO v_pred_last_shard
                FROM pg_dist_shard
                WHERE logicalrelid = v_pred_last_regclass
                AND shardminvalue = v_shardminvalue;

                IF v_pred_last_regclass IS NOT NULL AND v_pred_last_shard IS NULL THEN
                    RAISE EXCEPTION 'could not resolve {pred_patch_last_table} shard for patch shardid %', v_patch_shardid;
                END IF;

                FOR v_lvl IN 8..12 LOOP
                    v_shift := 12 - v_lvl;

                    SELECT TG_TABLE_SCHEMA || '.' || '{cm_prefix}' || v_lvl::text || '_' || shardid::text
                    INTO v_cm_shard
                    FROM pg_dist_shard
                    WHERE logicalrelid = ('{cm_prefix}' || v_lvl::text)::regclass
                    AND shardminvalue = v_shardminvalue;

                    IF v_pred_last_shard IS NULL THEN
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

        def _attach_insert_triggers_sql(table: str) -> str:
            return f"""
            SELECT run_command_on_shards(
                '{table}',
                $cmd$
                    CREATE TRIGGER trg_update_cm AFTER INSERT ON %s
                    REFERENCING NEW TABLE AS new_rows
                    FOR EACH STATEMENT
                    EXECUTE FUNCTION {insert_fn_name}()
                $cmd$
            );
            """

        attach_update_triggers_sql = f"""
            SELECT run_command_on_shards(
                '{patch_table}',
                $cmd$
                    CREATE TRIGGER trg_update_cm_on_patch_update AFTER UPDATE ON %s
                    REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
                    FOR EACH STATEMENT
                    EXECUTE FUNCTION {update_fn_name}()
                $cmd$
            );
            """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(insert_trigger_fn_sql)
                cur.execute(f"SELECT run_command_on_workers($outer${insert_trigger_fn_sql}$outer$);")
                print(f"INSERT trigger function {insert_fn_name} created on coordinator and workers.")

                cur.execute(update_trigger_fn_sql)
                cur.execute(f"SELECT run_command_on_workers($outer${update_trigger_fn_sql}$outer$);")
                print(f"UPDATE trigger function {update_fn_name} created on coordinator and workers.")

                cur.execute(_attach_insert_triggers_sql(pred_patch_table))
                print(f"Per-shard INSERT triggers installed on {pred_patch_table} shards.")

                cur.execute(_attach_insert_triggers_sql(pred_patch_last_table))
                print(f"Per-shard INSERT triggers installed on {pred_patch_last_table} shards.")

                cur.execute(attach_update_triggers_sql)
                print(f"Per-shard UPDATE triggers installed on {patch_table} shards.")

            conn.commit()

        print(f"\nAll per-shard triggers for project {project_id} installed.")


class CitusWorkerClient(CitusHeadClient):
    """Connection factory for direct shard-level access on a Citus worker node.

    Subclasses :class:`CitusHeadClient` with worker-specific default connection
    parameters.  Use this client with
    :class:`~patchsorter.db.unit_of_work.CitusWorkerUnitOfWork` to query shard
    tables directly on the worker without routing through the coordinator.

    Note:
        Reference tables (``project``, ``image``, ``label_class``, etc.) are
        replicated to workers and can be queried, but should be mutated only
        through the coordinator.
    """

    def __init__(
        self,
        host: str = CITUS_WORKER_HOST,
        port: int = CITUS_WORKER_PORT,
        dbname: str = CITUS_WORKER_DB,
        user: str = CITUS_WORKER_USER,
        password: str = CITUS_WORKER_PASSWORD,
    ) -> None:
        """Initialise the worker client.

        Args:
            host: Hostname or IP address of the Citus worker node.
            port: PostgreSQL port on the worker.
            dbname: Database name.
            user: PostgreSQL user.
            password: PostgreSQL password.
        """
        super().__init__(
            host=host,
            port=port,
            dbname=dbname,
            user=user,
            password=password,
        )

