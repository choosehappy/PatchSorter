"""Live-DB tests for CandidatePool (in-memory scores) and ScoreWriter (DB scores).

Both classes run against the real Citus test database. ``ScoreWriter`` flushes
from a background thread on its own connection, so the fixture commits its
seed data (rather than using the rolled-back ``db_session``) and removes it on
teardown.
"""
import math
import time
import uuid
from typing import Any, Dict, List

import numpy as np
import pytest
import torch
from sqlalchemy import text

from patchsorter.config.constants import UNASSIGNED_CLASS_ID
from patchsorter.db.head_client import ImageStore, LabelClassStore, PatchStore
from patchsorter.dl import datasets
from patchsorter.dl.datasets import GT_SCORE_IN_MEMORY_DECAY, CandidatePool
from patchsorter.dl.scoring import ScoreWriter

PROJECT_ID = 1
FAKE_SHARD_ID = 900001


@pytest.fixture
def seeded(test_db, _project1_tables, monkeypatch) -> Dict[str, Any]:
    """Commit a project with three labeled patches and one unlabeled patch."""
    with test_db.get_session() as s:
        s.execute(
            text(
                "INSERT INTO project (project_id, project_name, description) "
                "OVERRIDING SYSTEM VALUE VALUES (1, 'pool-test', 'pool-test')"
            )
        )
        lc = LabelClassStore(s).create(PROJECT_ID, "Tumor", "#FF0000")
        image = ImageStore(s).create(
            project_id=PROJECT_ID, name="s.svs", image_path="/data/s.svs", base_mag=20.0,
            base_width=1000, base_height=1000, deepzoom_tilesize=256,
        )
        store = PatchStore(PROJECT_ID, s)
        labeled = [uuid.uuid4() for _ in range(3)]
        unlabeled = uuid.uuid4()
        store.bulk_insert(
            [(u, lc["label_class_id"], image["image_id"], 2.0, i, i, None, bytes(16)) for i, u in enumerate(labeled)]
            + [(unlabeled, UNASSIGNED_CLASS_ID, image["image_id"], 2.0, 9, 9, None, bytes(16))]
        )
        rows = s.execute(
            text("SELECT patch_id, patch_uid FROM project1_patch ORDER BY patch_id")
        ).fetchall()
        # The test cluster has no Citus workers, so project1_patch is a plain table with no
        # physical shards. A view named like a shard stands in for the single local shard.
        s.execute(text(f"CREATE VIEW project1_patch_{FAKE_SHARD_ID} AS SELECT * FROM project1_patch"))

    by_uid = {r.patch_uid: r.patch_id for r in rows}
    monkeypatch.setattr(datasets.worker_client, "get_client", lambda: test_db)

    yield {
        "sm": test_db,
        "ids": [by_uid[u] for u in labeled],
        "unlabeled_id": by_uid[unlabeled],
        "shards": [FAKE_SHARD_ID],
    }

    with test_db.get_session() as s:
        s.execute(text(f"DROP VIEW IF EXISTS project1_patch_{FAKE_SHARD_ID}"))
        for tbl in ("project1_pred_patch_latest", "project1_patch"):
            s.execute(text(f"DELETE FROM {tbl}"))
        s.execute(text("DELETE FROM label_class WHERE project_id = 1"))
        s.execute(text("DELETE FROM image WHERE project_id = 1"))
        s.execute(text("DELETE FROM project WHERE project_id = 1"))


def db_priorities(sm) -> Dict[int, Any]:
    with sm.get_session() as s:
        return {r.patch_id: r.train_priority for r in s.execute(text("SELECT patch_id, train_priority FROM project1_patch"))}


def set_priorities(sm, values: Dict[int, Any]) -> None:
    with sm.get_session() as s:
        for pid, prio in values.items():
            s.execute(text("UPDATE project1_patch SET train_priority = :p WHERE patch_id = :i"), {"p": prio, "i": pid})


def make_pool(seeded, pool_size=2048) -> CandidatePool:
    return CandidatePool(PROJECT_ID, seeded["shards"], pool_size=pool_size)


def make_writer(seeded, **kw) -> ScoreWriter:
    kw.setdefault("flush_interval_s", 0.05)
    return ScoreWriter(seeded["sm"], PROJECT_ID, **kw)


def wait_for(cond, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def scores_by_id(pool: CandidatePool) -> Dict[int, float]:
    return {r["patch_id"]: float(s) for r, s in zip(pool._rows, pool._scores)}


# --------------------------------------------------------------------------
# CandidatePool
# --------------------------------------------------------------------------

class TestCandidatePool:
    def test_empty_before_refresh(self, seeded):
        pool = make_pool(seeded)
        assert pool.is_empty
        assert pool.draw_batch(5) == []

    def test_refresh_loads_only_labeled_rows_with_init_score(self, seeded):
        pool = make_pool(seeded)
        pool.refresh()
        assert {r["patch_id"] for r in pool._rows} == set(seeded["ids"])
        assert seeded["unlabeled_id"] not in scores_by_id(pool)
        np.testing.assert_allclose(pool._scores, datasets.GT_SCORE_INIT)
        assert pool._scores.dtype == np.float64

    def test_refresh_computes_rarity_from_fractional_priority(self, seeded):
        a, b, c = seeded["ids"]
        set_priorities(seeded["sm"], {a: 5.5, b: 5.2})
        pool = make_pool(seeded)
        pool.refresh()
        scores = scores_by_id(pool)
        assert scores[a] == pytest.approx(0.5, abs=1e-6)
        assert scores[b] == pytest.approx(0.2, abs=1e-6)
        assert scores[c] == datasets.GT_SCORE_INIT
        assert pool._rows[0]["patch_id"] == c  # unscored ranks first

    def test_refresh_respects_pool_size(self, seeded):
        pool = make_pool(seeded, pool_size=2)
        pool.refresh()
        assert len(pool._rows) == 2

    def test_refresh_picks_up_db_changes_and_discards_memory_decay(self, seeded):
        a = seeded["ids"][0]
        set_priorities(seeded["sm"], {a: 7.9})
        pool = make_pool(seeded)
        pool.refresh()
        idx = next(i for i, r in enumerate(pool._rows) if r["patch_id"] == a)
        pool.decay_in_memory_score(idx)
        decayed = scores_by_id(pool)[a]
        assert decayed == pytest.approx(0.9 * GT_SCORE_IN_MEMORY_DECAY, abs=1e-6)

        set_priorities(seeded["sm"], {a: 7.95})
        pool.refresh()
        assert scores_by_id(pool)[a] == pytest.approx(0.95, abs=1e-6)

    def test_refresh_empty_when_no_labeled_patches(self, seeded):
        with seeded["sm"].get_session() as s:
            s.execute(text("UPDATE project1_patch SET label_class_id = :u"), {"u": UNASSIGNED_CLASS_ID})
        pool = make_pool(seeded)
        pool.refresh()
        assert pool.is_empty

    def test_draw_batch_distinct_and_capped(self, seeded):
        pool = make_pool(seeded)
        pool.refresh()
        picks = pool.draw_batch(10)
        idxs = [i for _, i in picks]
        assert len(picks) == 3 and len(set(idxs)) == 3
        assert all(row is pool._rows[i] for row, i in picks)

    def test_draw_batch_biased_by_score(self, seeded):
        a, b, c = seeded["ids"]
        set_priorities(seeded["sm"], {a: 1.99, b: 1.001, c: 1.001})
        pool = make_pool(seeded)
        pool.refresh()
        np.random.seed(0)
        hits = sum(pool.draw_batch(1)[0][0]["patch_id"] == a for _ in range(300))
        assert hits > 250

    def test_draw_batch_zero_weights_falls_back_to_uniform(self, seeded):
        set_priorities(seeded["sm"], {i: 4.0 for i in seeded["ids"]})  # rarity 0
        pool = make_pool(seeded)
        pool.refresh()
        assert np.allclose(pool._scores, 0)
        assert len(pool.draw_batch(3)) == 3

    def test_decay_in_memory_score(self, seeded):
        pool = make_pool(seeded)
        pool.refresh()
        before = pool._scores.copy()
        pool.decay_in_memory_score(1)
        pool.decay_in_memory_score(1)
        assert pool._scores[1] == pytest.approx(before[1] * GT_SCORE_IN_MEMORY_DECAY ** 2)
        assert pool._scores[0] == before[0]

    @pytest.mark.parametrize("idx", [-1, 3, 100])
    def test_decay_out_of_range_is_noop(self, seeded, idx):
        pool = make_pool(seeded)
        pool.refresh()
        before = pool._scores.copy()
        pool.decay_in_memory_score(idx)
        np.testing.assert_array_equal(pool._scores, before)

    def test_repeated_decay_shifts_draws_to_other_candidates(self, seeded):
        a, b, c = seeded["ids"]
        set_priorities(seeded["sm"], {a: 1.9, b: 1.001, c: 1.001})
        pool = make_pool(seeded)
        pool.refresh()
        idx = next(i for i, r in enumerate(pool._rows) if r["patch_id"] == a)
        for _ in range(60):
            pool.decay_in_memory_score(idx)
        np.random.seed(1)
        hits = sum(pool.draw_batch(1)[0][0]["patch_id"] == a for _ in range(200))
        assert hits < 20


# --------------------------------------------------------------------------
# ScoreWriter
# --------------------------------------------------------------------------

class TestScoreWriter:
    def test_close_flushes_pending_to_db(self, seeded):
        a, b, c = seeded["ids"]
        w = make_writer(seeded, batch_size=1000, flush_interval_s=30)
        w.enqueue(torch.tensor([a, b]), torch.tensor([3.25, 4.5]))
        w.close()
        prios = db_priorities(seeded["sm"])
        assert prios[a] == pytest.approx(3.25)
        assert prios[b] == pytest.approx(4.5)
        assert prios[c] is None
        assert prios[seeded["unlabeled_id"]] is None

    def test_batch_size_triggers_flush_before_close(self, seeded):
        a, b, _ = seeded["ids"]
        w = make_writer(seeded, batch_size=2, flush_interval_s=30)
        try:
            w.enqueue(torch.tensor([a, b]), torch.tensor([1.5, 2.5]))
            wait_for(lambda: db_priorities(seeded["sm"])[b] is not None)
            assert db_priorities(seeded["sm"])[a] == pytest.approx(1.5)
        finally:
            w.close()

    def test_interval_triggers_flush_below_batch_size(self, seeded):
        c = seeded["ids"][2]
        w = make_writer(seeded, batch_size=1000, flush_interval_s=0.05)
        try:
            w.enqueue(torch.tensor([c]), torch.tensor([9.75]))
            wait_for(lambda: db_priorities(seeded["sm"])[c] is not None)
            assert db_priorities(seeded["sm"])[c] == pytest.approx(9.75)
        finally:
            w.close()

    def test_scalar_tensors(self, seeded):
        a = seeded["ids"][0]
        w = make_writer(seeded, batch_size=1000, flush_interval_s=30)
        w.enqueue(torch.tensor(a), torch.tensor(2.5))
        w.close()
        assert db_priorities(seeded["sm"])[a] == pytest.approx(2.5)

    def test_later_score_overwrites_earlier_over_time(self, seeded):
        a = seeded["ids"][0]
        w = make_writer(seeded, batch_size=1, flush_interval_s=30)
        try:
            for score in (1.25, 2.5, 3.75):
                w.enqueue(torch.tensor([a]), torch.tensor([score]))
                wait_for(lambda: db_priorities(seeded["sm"])[a] == pytest.approx(score))
        finally:
            w.close()

    def test_duplicate_ids_in_one_flush_apply_in_order(self, seeded):
        a = seeded["ids"][0]
        w = make_writer(seeded, batch_size=1000, flush_interval_s=30)
        w.enqueue(torch.tensor([a, a]), torch.tensor([1.25, 5.5]))
        w.close()
        assert db_priorities(seeded["sm"])[a] == pytest.approx(5.5)

    def test_flush_failure_is_logged_and_writer_keeps_working(self, seeded, caplog, monkeypatch):
        a, b, _ = seeded["ids"]
        from patchsorter.dl import scoring

        real = scoring.PatchStore.update_train_priority
        calls = {"n": 0}

        def flaky(self, updates):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("db down")
            return real(self, updates)

        monkeypatch.setattr(scoring.PatchStore, "update_train_priority", flaky)
        w = make_writer(seeded, batch_size=1, flush_interval_s=30)
        try:
            w.enqueue(torch.tensor([a]), torch.tensor([1.5]))
            wait_for(lambda: "ScoreWriter flush failed" in caplog.text)
            assert db_priorities(seeded["sm"])[a] is None

            w.enqueue(torch.tensor([b]), torch.tensor([2.5]))
            wait_for(lambda: db_priorities(seeded["sm"])[b] is not None)
        finally:
            w.close()

    def test_close_without_updates_leaves_db_untouched(self, seeded):
        make_writer(seeded).close()
        assert all(v is None for v in db_priorities(seeded["sm"]).values())

    def test_close_stops_thread(self, seeded):
        w = make_writer(seeded)
        w.close()
        assert not w._thread.is_alive()


# --------------------------------------------------------------------------
# CandidatePool + ScoreWriter over time
# --------------------------------------------------------------------------

class TestPoolAndWriterOverTime:
    def test_scores_written_then_visible_after_refresh(self, seeded):
        a, b, c = seeded["ids"]
        pool = make_pool(seeded)
        pool.refresh()
        assert all(r["train_priority"] is None for r in pool._rows)

        writer = make_writer(seeded, batch_size=1000, flush_interval_s=30)
        writer.enqueue(torch.tensor([a, b]), torch.tensor([10.875, 10.125]))
        writer.close()

        # In-memory view is stale until the next refresh.
        assert all(r["train_priority"] is None for r in pool._rows)

        pool.refresh()
        scores = scores_by_id(pool)
        assert scores[a] == pytest.approx(0.875, abs=1e-6)
        assert scores[b] == pytest.approx(0.125, abs=1e-6)
        assert scores[c] == datasets.GT_SCORE_INIT
        assert pool._rows[0]["patch_id"] == c

    def test_stale_rows_decay_relative_to_newer_iterations(self, seeded):
        a, b, _ = seeded["ids"]
        set_priorities(seeded["sm"], {a: 1.5, b: 1.5})
        pool = make_pool(seeded)
        pool.refresh()

        writer = make_writer(seeded, batch_size=1000, flush_interval_s=30)
        writer.enqueue(torch.tensor([b]), torch.tensor([101.5]))
        writer.close()
        pool.refresh()

        scores = scores_by_id(pool)
        assert scores[b] == pytest.approx(0.5, abs=1e-6)
        assert scores[a] == pytest.approx(0.5 * math.exp(-datasets.GT_SCORE_DECAY * 100), abs=1e-6)

    def test_draw_decay_write_refresh_cycle(self, seeded):
        pool = make_pool(seeded)
        writer = make_writer(seeded, batch_size=1000, flush_interval_s=30)
        pool.refresh()

        np.random.seed(0)
        picks = pool.draw_batch(2)
        for _, idx in picks:
            pool.decay_in_memory_score(idx)
        drawn = [row["patch_id"] for row, _ in picks]

        # Memory decays immediately; the DB only changes once the writer flushes.
        for _, idx in picks:
            assert pool._scores[idx] == pytest.approx(datasets.GT_SCORE_INIT * GT_SCORE_IN_MEMORY_DECAY)
        assert all(v is None for v in db_priorities(seeded["sm"]).values())

        writer.enqueue(torch.tensor(drawn), torch.tensor([5.25] * len(drawn)))
        writer.close()
        prios = db_priorities(seeded["sm"])
        assert all(prios[p] == pytest.approx(5.25) for p in drawn)

        pool.refresh()
        scores = scores_by_id(pool)
        undrawn = (set(seeded["ids"]) - set(drawn)).pop()
        assert scores[undrawn] == datasets.GT_SCORE_INIT
        assert all(scores[p] == pytest.approx(0.25, abs=1e-6) for p in drawn)
