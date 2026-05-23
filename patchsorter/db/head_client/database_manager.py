from patchsorter.db.utils import SessionManager


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

    def drop_all_tables(self) -> None:
        statements = [
            "DROP TABLE IF EXISTS settings CASCADE;",
            "DROP TABLE IF EXISTS log CASCADE;",
            "DROP TABLE IF EXISTS label_class CASCADE;",
            "DROP TABLE IF EXISTS image CASCADE;",
            "DROP TABLE IF EXISTS project CASCADE;",
        ]
        with self.sm.get_connection() as conn:
            with conn.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)
            conn.commit()

    def setup_schema(self) -> None:
        schema_statements = [
            """CREATE TABLE IF NOT EXISTS project (
                project_id   SERIAL    PRIMARY KEY,
                project_name TEXT      NOT NULL,
                description  TEXT
            );""",
            """CREATE TABLE IF NOT EXISTS image (
                image_id          SERIAL    PRIMARY KEY,
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
                project_id      INT       NOT NULL REFERENCES project(project_id),
                name            TEXT      NOT NULL,
                color_code      TEXT,
                event_ts        TIMESTAMP NOT NULL,
                UNIQUE(project_id, name)
            );""",
            """CREATE TABLE IF NOT EXISTS settings (
                setting_id    SERIAL  PRIMARY KEY,
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
        with self.sm.get_connection() as conn:
            with conn.cursor() as cur:
                for stmt in schema_statements:
                    cur.execute(stmt)
                for stmt in distribution_statements:
                    try:
                        cur.execute(stmt)
                    except Exception as e:
                        print(f"Distribution command failed (may already be distributed): {e}")
            conn.commit()

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
        last_table = f"project{n}_pred_patch_last"
        latest_table = f"project{n}_pred_patch_latest"
        tmp_table = f"project{n}_pred_patch_tmp"
        with self.sm.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"TRUNCATE TABLE {last_table};")
                cur.execute(f"ALTER TABLE {last_table} RENAME TO {tmp_table};")
                cur.execute(f"ALTER TABLE {latest_table} RENAME TO {last_table};")
                cur.execute(f"ALTER TABLE {tmp_table} RENAME TO {latest_table};")
            conn.commit()