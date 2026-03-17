"""
Populate the hierarchical aggregation tables with synthetic labelled-point data.

Usage:
    python populate_db.py
"""
import random
import psycopg2
from utils import create_agg_tables, populate_agg_tables, create_patch_tables

DATABASE_URL = "dbname=testdb user=testuser password=mypassword host=prototyping-pg-1"

NUM_POINTS   = 50_000
NUM_CLASSES  = 5      # labels 0..4
SPACE_SIZE   = 256.0  # world coordinate range [0, SPACE_SIZE)
CELL_SIZE    = SPACE_SIZE  # one level-0 cell covers the whole space


def generate_points(n: int, num_classes: int, space: float):
    """Generate n random (x, y, pred_label, gt_label) tuples with cluster structure."""
    rng = random.Random(42)
    points = []
    # Create one cluster centre per class pair
    centres = {
        (p, g): (rng.uniform(0, space), rng.uniform(0, space))
        for p in range(num_classes)
        for g in range(num_classes)
    }
    for _ in range(n):
        pred = rng.randrange(num_classes)
        gt   = rng.randrange(num_classes)
        cx, cy = centres[(pred, gt)]
        x = max(0.0, min(space - 1e-6, cx + rng.gauss(0, space / 20)))
        y = max(0.0, min(space - 1e-6, cy + rng.gauss(0, space / 20)))
        points.append((x, y, pred, gt))
    return points


def main():
    conn = psycopg2.connect(DATABASE_URL)
    print("Connected to database.")

    print("Creating base tables...")
    create_patch_tables(conn, if_not_exists=True)

    print("Creating aggregation tables...")
    create_agg_tables(conn, cell_size=CELL_SIZE, if_not_exists=True)

    print(f"Generating {NUM_POINTS:,} synthetic points...")
    points = generate_points(NUM_POINTS, NUM_CLASSES, SPACE_SIZE)

    print("Populating aggregation tables...")
    populate_agg_tables(conn, points, cell_size=CELL_SIZE)

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
