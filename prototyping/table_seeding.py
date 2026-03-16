#!/usr/bin/env python3
"""
table_seeding.py – Create and populate the bench_patches table.

Usage:
    python table_seeding.py [--rows N] [--workers W] [--drop]

Options:
    --rows N      Total rows to insert (default: 1_000_000_000)
    --workers W   Parallel worker connections (default: 8)
    --drop        DROP and recreate the table before seeding
"""

import argparse
import sys
import threading
import time

import psycopg2

# ---------------------------------------------------------------------------
# Parameters – mirror what the notebook uses
# ---------------------------------------------------------------------------
DATABASE_URL = "dbname=testdb user=testuser password=mypassword host=prototyping-pg-1"

CELL_SIZE   = 1.0
LEVEL       = 11
COORD_RANGE = 1.0

# ---------------------------------------------------------------------------
# DDL helpers
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
    CREATE UNLOGGED TABLE bench_patches (
        id                BIGSERIAL PRIMARY KEY,
        embed_x           FLOAT,
        embed_y           FLOAT,
        grid_id_ij        BIGINT,
        grid_id_z         BIGINT,
        grid_i_indexed    BIGINT,
        grid_j_indexed    BIGINT,
        grid_i_unindexed  BIGINT,
        grid_j_unindexed  BIGINT
    );
"""

CREATE_MORTON_FN_SQL = """
    CREATE OR REPLACE FUNCTION encode_morton_cell(x FLOAT, y FLOAT,
                                                  level INT, cell_size FLOAT)
    RETURNS BIGINT LANGUAGE plpgsql IMMUTABLE STRICT PARALLEL SAFE AS $$
    DECLARE
        scaled_size FLOAT  := cell_size / (2.0 ^ level);
        i           BIGINT := floor(x / scaled_size)::BIGINT & 536870911;
        j           BIGINT := floor(y / scaled_size)::BIGINT & 536870911;
        code        BIGINT := 0;
        bit         INT;
    BEGIN
        FOR bit IN 0..28 LOOP
            code := code
                  | (((i >> bit) & 1) << (2 * bit))
                  | (((j >> bit) & 1) << (2 * bit + 1));
        END LOOP;
        RETURN (level::BIGINT << 58) | code;
    END;
    $$;
"""

CREATE_IJ_FN_SQL = """
    CREATE OR REPLACE FUNCTION encode_ij_cell(x FLOAT, y FLOAT,
                                              level INT, cell_size FLOAT)
    RETURNS BIGINT LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
        SELECT (level::BIGINT << 58)
             | ((floor(x / (cell_size / (2.0^level)))::BIGINT & 536870911) << 29)
             |  (floor(y / (cell_size / (2.0^level)))::BIGINT & 536870911)
    $$;
"""


def setup_schema(drop: bool = False) -> bool:
    """Create table + helper functions.  Returns True if creation was needed."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            if drop:
                cur.execute("DROP TABLE IF EXISTS bench_patches;")
                conn.commit()
                print("Dropped existing bench_patches table.")

            cur.execute("SELECT to_regclass('public.bench_patches') IS NOT NULL;")
            exists = cur.fetchone()[0]

        if exists:
            print("bench_patches already exists — skipping schema creation.")
            return False

        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            cur.execute(CREATE_MORTON_FN_SQL)
            cur.execute(CREATE_IJ_FN_SQL)
        conn.commit()
        print("Table and helper functions created.")
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Population – parallel server-side generate_series workers
# ---------------------------------------------------------------------------

def _worker(worker_id: int, row_start: int, row_count: int, errors: list) -> None:
    """Open a dedicated connection and INSERT one slice via generate_series."""
    try:
        wconn = psycopg2.connect(DATABASE_URL)
        wconn.autocommit = True
        with wconn.cursor() as cur:
            cur.execute("SET synchronous_commit = OFF;")
            cur.execute(f"""
                INSERT INTO bench_patches
                    (embed_x, embed_y,
                     grid_id_ij, grid_id_z,
                     grid_i_indexed,   grid_j_indexed,
                     grid_i_unindexed, grid_j_unindexed)
                SELECT
                    x,
                    y,
                    encode_ij_cell    (x, y, {LEVEL}, {CELL_SIZE}),
                    encode_morton_cell(x, y, {LEVEL}, {CELL_SIZE}),
                    floor(x / ({CELL_SIZE} / (2.0^{LEVEL})))::BIGINT & 536870911,
                    floor(y / ({CELL_SIZE} / (2.0^{LEVEL})))::BIGINT & 536870911,
                    floor(x / ({CELL_SIZE} / (2.0^{LEVEL})))::BIGINT & 536870911,
                    floor(y / ({CELL_SIZE} / (2.0^{LEVEL})))::BIGINT & 536870911
                FROM (
                    SELECT
                        random() * {COORD_RANGE} AS x,
                        random() * {COORD_RANGE} AS y
                    FROM generate_series({row_start}, {row_start + row_count - 1})
                ) pts;
            """)
        wconn.close()
        print(f"  worker {worker_id:2d} done  ({row_count/1e6:.1f}M rows)", flush=True)
    except Exception as exc:
        errors.append((worker_id, exc))
        print(f"  worker {worker_id:2d} ERROR: {exc}", flush=True)


def populate(total_rows: int = 1_000_000_000, num_workers: int = 8) -> None:
    """Seed bench_patches with *total_rows* rows using *num_workers* parallel connections."""
    rows_per_worker = total_rows // num_workers
    errors: list = []

    print(f"Seeding {total_rows:,} rows with {num_workers} parallel workers …")
    t0 = time.time()

    threads = []
    for wid in range(num_workers):
        start = wid * rows_per_worker
        count = rows_per_worker if wid < num_workers - 1 else total_rows - start
        t = threading.Thread(target=_worker, args=(wid, start, count, errors), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    elapsed = time.time() - t0

    if errors:
        print(f"\n{len(errors)} worker(s) failed:")
        for wid, exc in errors:
            print(f"  worker {wid}: {exc}")
        sys.exit(1)

    rate = total_rows / elapsed / 1e6
    print(f"\nAll {num_workers} workers finished in {elapsed/60:.1f} min  ({rate:.2f}M rows/s)")

    # Verify
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM bench_patches;")
        actual = cur.fetchone()[0]
    conn.close()
    print(f"Actual rows in table: {actual:,}")



def create_indexes() -> None:
    """Build B-tree indexes on bench_patches and run ANALYZE."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0;")

            # index_name -> column expression
            indexes = [
                ("idx_bench_ij", "grid_id_ij"),
                ("idx_bench_z", "grid_id_z"),
                ("idx_bench_i_j", "grid_i_indexed, grid_j_indexed"),  # composite index
            ]

            for idx_name, cols in indexes:
                # Skip if index already exists
                cur.execute(
                    "SELECT 1 FROM pg_indexes WHERE indexname = %s;",
                    (idx_name,),
                )
                if cur.fetchone():
                    print(f"  index {idx_name} already exists — skipping.")
                    continue

                print(f"  building {idx_name} on ({cols}) …", flush=True)
                t0 = time.time()

                cur.execute(
                    f"CREATE INDEX {idx_name} ON bench_patches ({cols});"
                )

                conn.commit()
                print(f"    done in {time.time() - t0:.1f}s")

            # grid_i_unindexed / grid_j_unindexed intentionally have NO index
            print("Running ANALYZE …", flush=True)
            cur.execute("ANALYZE bench_patches;")
            conn.commit()
            print("ANALYZE done.")
    finally:
        conn.close()




# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create and seed the bench_patches table.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--rows",    type=int, default=1_000_000_000, help="Total rows to insert")
    parser.add_argument("--workers", type=int, default=8,             help="Parallel worker connections")
    parser.add_argument("--drop",    action="store_true",             help="DROP the table before seeding")
    args = parser.parse_args()

    created = setup_schema(drop=args.drop)
    if created:
        populate(total_rows=args.rows, num_workers=args.workers)
        create_indexes()
    else:
        print("Nothing to do — use --drop to re-seed.")


if __name__ == "__main__":
    main()
