import io
import sqlite3
import tempfile
import time

import numpy as np
import torch

from sqlite_dataset import GTEnrichedDataset
from score_writer import ScoreWriter
from utils import LabeledRateTracker


def _serialize_patch(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def test_gt_enriched_dataset_initializes_score_column(tmp_path):
    db_path = tmp_path / "patches.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE mitosis_patches(id INTEGER PRIMARY KEY, patch BLOB, tmp_label INTEGER)"
        )
        for idx in range(5):
            patch = _serialize_patch(np.full((60, 60, 3), idx, dtype=np.uint8))
            label = -1 if idx < 2 else idx - 2
            conn.execute(
                "INSERT INTO mitosis_patches (patch, tmp_label) VALUES (?, ?)",
                (patch, label),
            )
        conn.commit()

    dataset = GTEnrichedDataset(str(db_path), nviews=1, transforms=None, enrichment_rate=1.0)

    with sqlite3.connect(db_path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(mitosis_patches)")]
        assert "score" in columns

    image, label, orig, index = dataset[0]
    assert isinstance(label, int)
    assert isinstance(index, int)
    assert isinstance(image, np.ndarray)
    assert isinstance(orig, np.ndarray)


def test_gt_enriched_dataset_uses_bounded_pool(tmp_path):
    db_path = tmp_path / "patches_pool.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE mitosis_patches(id INTEGER PRIMARY KEY, patch BLOB, tmp_label INTEGER, score REAL)"
        )
        for idx in range(10):
            patch = _serialize_patch(np.full((60, 60, 3), idx, dtype=np.uint8))
            conn.execute(
                "INSERT INTO mitosis_patches (patch, tmp_label, score) VALUES (?, ?, ?)",
                (patch, idx % 3, float(10 - idx)),
            )
        conn.commit()

    dataset = GTEnrichedDataset(
        str(db_path),
        nviews=1,
        transforms=None,
        enrichment_rate=1.0,
        pool_size=3,
    )

    assert dataset._candidate_count == 3
    top_scores = sorted(dataset._candidate_scores[: dataset._candidate_count], reverse=True)
    assert top_scores == [10.0, 9.0, 8.0]


def test_gt_enriched_dataset_uses_label_tracker_rarity(tmp_path):
    db_path = tmp_path / "patches_label.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE mitosis_patches(id INTEGER PRIMARY KEY, patch BLOB, tmp_label INTEGER, score REAL)"
        )
        for idx in range(5):
            patch = _serialize_patch(np.full((60, 60, 3), idx, dtype=np.uint8))
            conn.execute(
                "INSERT INTO mitosis_patches (patch, tmp_label, score) VALUES (?, ?, ?)",
                (patch, idx % 2, float(5 - idx)),
            )
        conn.commit()

    tracker = LabeledRateTracker(nclasses=2)
    tracker.update(torch.tensor([0, 0, 1], dtype=torch.int64))

    dataset = GTEnrichedDataset(
        str(db_path),
        nviews=1,
        transforms=None,
        enrichment_rate=1.0,
        pool_size=2,
        label_tracker=tracker,
    )

    rarity_map = dataset._get_rarity_map()
    assert rarity_map is not None
    assert set(rarity_map.keys()) == {0, 1}
    assert rarity_map[1] > rarity_map[0]


def test_score_writer_batches_and_flushes(tmp_path):
    db_path = tmp_path / "writer_test.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE mitosis_patches(id INTEGER PRIMARY KEY, patch BLOB, tmp_label INTEGER, score REAL)"
        )
        for idx in range(10):
            conn.execute(
                "INSERT INTO mitosis_patches (id, patch, tmp_label, score) VALUES (?, ?, ?, ?)",
                (idx + 1, b"dummy", 0, 1.0),
            )
        conn.commit()

    writer = ScoreWriter(str(db_path))

    for idx in range(5):
        writer.enqueue(idx + 1, 0.5 * (idx + 1))

    writer.close()
    time.sleep(0.5)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, score FROM mitosis_patches WHERE id <= 5 ORDER BY id")
        rows = cursor.fetchall()

    expected_scores = {1: 0.5, 2: 1.0, 3: 1.5, 4: 2.0, 5: 2.5}
    for row_id, score in rows:
        assert score == expected_scores[row_id], f"Row {row_id}: expected {expected_scores[row_id]}, got {score}"


def test_gt_enriched_dataset_refresh_pool(tmp_path):
    """Test refresh() method to update pool with newly labeled items."""
    db_path = tmp_path / "refresh_test.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE mitosis_patches(id INTEGER PRIMARY KEY, patch BLOB, tmp_label INTEGER, score REAL)"
        )
        for idx in range(10):
            patch = _serialize_patch(np.random.rand(32, 32, 3).astype(np.float32))
            label = 0 if idx < 3 else -1  # Only first 3 are labeled initially
            conn.execute(
                "INSERT INTO mitosis_patches (id, patch, tmp_label, score) VALUES (?, ?, ?, ?)",
                (idx + 1, patch, label, 1.0),
            )
        conn.commit()

    dataset = GTEnrichedDataset(str(db_path), pool_size=5, enrichment_rate=0.5)

    # Initially, only 3 labeled items
    assert dataset._candidate_count == 3
    initial_ids = set(dataset._candidate_ids[: dataset._candidate_count].tolist())

    # Label more items with high scores in database
    with sqlite3.connect(db_path) as conn:
        for idx in range(3, 6):
            conn.execute(
                "UPDATE mitosis_patches SET tmp_label = 0, score = 2.0 WHERE id = ?",
                (idx + 1,),
            )
        conn.commit()

    # After refresh, pool should include new labeled items
    dataset.refresh()

    assert dataset._candidate_count == 5  # Pool size is 5
    new_ids = set(dataset._candidate_ids[: dataset._candidate_count].tolist())

    # Should have new labeled items in pool (with higher scores)
    assert new_ids != initial_ids

