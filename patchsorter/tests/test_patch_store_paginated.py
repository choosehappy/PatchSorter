"""Unit tests for PatchStore._paginated_pred_join and .get_patches_within_grid_bbox."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from patchsorter.db.head_client import PatchStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_patch_ids(session: Session, project_id: int) -> List[int]:
    """Return patch_ids for project{N}_patch ordered by patch_id."""
    rows = session.execute(
        text(f"SELECT patch_id FROM project{project_id}_patch ORDER BY patch_id")
    ).fetchall()
    return [r[0] for r in rows]


def _insert_latest(session: Session, project_id: int, records: List[tuple]) -> None:
    """Insert directly into pred_patch_latest via upsert_predictions."""
    PatchStore(project_id, session).upsert_predictions(records)


def _insert_last(session: Session, project_id: int, records: List[tuple]) -> None:
    """Insert rows into pred_patch_last using raw SQL (no store method exists for _last)."""
    if not records:
        return
    table = f"project{project_id}_pred_patch_last"
    placeholders = ", ".join(
        f"(:patch_id_{i}, :embed_x_{i}, :embed_y_{i}, :grid_cell_i_{i}, :grid_cell_j_{i}, :label_class_id_{i})"
        for i in range(len(records))
    )
    params: Dict[str, Any] = {}
    for i, (pid, ex, ey, gi, gj, lc) in enumerate(records):
        params[f"patch_id_{i}"] = pid
        params[f"embed_x_{i}"] = ex
        params[f"embed_y_{i}"] = ey
        params[f"grid_cell_i_{i}"] = gi
        params[f"grid_cell_j_{i}"] = gj
        params[f"label_class_id_{i}"] = lc
    session.execute(
        text(
            f"""
            INSERT INTO {table}
                (patch_id, embed_x, embed_y, grid_cell_i, grid_cell_j, label_class_id)
            VALUES {placeholders}
            ON CONFLICT (patch_id) DO UPDATE SET
                embed_x        = EXCLUDED.embed_x,
                embed_y        = EXCLUDED.embed_y,
                grid_cell_i    = EXCLUDED.grid_cell_i,
                grid_cell_j    = EXCLUDED.grid_cell_j,
                label_class_id = EXCLUDED.label_class_id
            """
        ),
        params,
    )


# ---------------------------------------------------------------------------
# Fixture: pred data seeded on top of example_project
#
# Patch layout (project_id=1, 5 patches total):
#
#   patch index | table(s)       | grid (i, j) | note
#   ------------|----------------|-------------|----------------------------------
#   0           | latest only    | (2, 3)      | inside test bbox
#   1           | latest only    | (2, 4)      | inside test bbox
#   2           | latest only    | (5, 5)      | outside test bbox
#   3           | last only      | (2, 3)      | inside test bbox, no latest row
#   4           | latest + last  | (2, 3)      | latest should take priority
#
# Test bbox used by get_patches_within_grid_bbox tests: i in [2,3], j in [3,4]
# Expected in-bbox patch indices: 0, 1, 3, 4  →  4 rows
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_preds(example_project: Dict[str, Any], db_session: Session) -> Dict[str, Any]:
    """Seed pred_patch_latest and pred_patch_last on top of example_project."""
    project_id: int = example_project["project"]["project_id"]
    lc_id: int = example_project["label_classes"][0]["label_class_id"]

    patch_ids = _get_patch_ids(db_session, project_id)
    assert len(patch_ids) == 5, "Expected 5 patches from example_project fixture"

    p0, p1, p2, p3, p4 = patch_ids

    # Clear existing predictions (distributed tables don't roll back properly)
    db_session.execute(text(f"DELETE FROM project{project_id}_pred_patch_latest"))
    db_session.execute(text(f"DELETE FROM project{project_id}_pred_patch_last"))
    db_session.flush()

    # pred_patch_latest rows
    _insert_latest(
        db_session,
        project_id,
        [
            (p0, 0.10, 0.20, 2, 3, lc_id),   # in bbox
            (p1, 0.11, 0.21, 2, 4, lc_id),   # in bbox
            (p2, 0.12, 0.22, 5, 5, lc_id),   # outside bbox
            # p3 intentionally omitted from latest
            (p4, 0.14, 0.24, 2, 3, lc_id),   # in bbox; also in last (different coords)
        ],
    )

    # pred_patch_last rows
    _insert_last(
        db_session,
        project_id,
        [
            (p3, 0.30, 0.31, 2, 3, lc_id),         # in bbox, no latest row
            (p4, 99.9, 99.9, 9, 9, lc_id),          # outside bbox if taken alone; latest wins
        ],
    )

    db_session.flush()

    return {
        **example_project,
        "patch_ids": patch_ids,
        "in_bbox_patch_ids": {p0, p1, p3, p4},
        "out_of_bbox_patch_ids": {p2},
    }


# ---------------------------------------------------------------------------
# _paginated_pred_join — direct tests
# ---------------------------------------------------------------------------

class TestPaginatedPredJoin:
    def test_returns_list_of_dicts(self, seeded_preds, db_session):
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store._paginated_pred_join(
            "grid_cell_i = :i AND grid_cell_j = :j",
            {"i": 2, "j": 3},
        )
        assert isinstance(rows, list)
        assert all(isinstance(r, dict) for r in rows)

    def test_filter_restricts_results(self, seeded_preds, db_session):
        """Only patches matching the filter are returned."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store._paginated_pred_join(
            "grid_cell_i = :i AND grid_cell_j = :j",
            {"i": 5, "j": 5},
        )
        assert len(rows) == 1
        assert rows[0]["grid_cell_i"] == 5
        assert rows[0]["grid_cell_j"] == 5

    def test_latest_wins_over_last(self, seeded_preds, db_session):
        """When a patch exists in both tables, latest values are returned (priority=1)."""
        project_id = seeded_preds["project"]["project_id"]
        p4 = seeded_preds["patch_ids"][4]
        store = PatchStore(project_id, db_session)

        rows = store._paginated_pred_join(
            "grid_cell_i = :i AND grid_cell_j = :j",
            {"i": 2, "j": 3},
        )
        p4_rows = [r for r in rows if r["patch_id"] == p4]
        assert len(p4_rows) == 1, "patch4 should appear exactly once (deduped by DISTINCT ON)"
        # Latest row has embed_x=0.14, last row has embed_x=99.9
        assert abs(p4_rows[0]["embed_x"] - 0.14) < 1e-6, "latest embed_x expected"
        assert p4_rows[0]["priority"] == 1

    def test_last_only_patch_is_returned(self, seeded_preds, db_session):
        """A patch that only exists in pred_patch_last is still returned."""
        project_id = seeded_preds["project"]["project_id"]
        p3 = seeded_preds["patch_ids"][3]
        store = PatchStore(project_id, db_session)

        rows = store._paginated_pred_join(
            "grid_cell_i = :i AND grid_cell_j = :j",
            {"i": 2, "j": 3},
        )
        p3_rows = [r for r in rows if r["patch_id"] == p3]
        assert len(p3_rows) == 1
        assert p3_rows[0]["priority"] == 2

    def test_limit_is_respected(self, seeded_preds, db_session):
        """limit parameter caps the number of rows returned."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store._paginated_pred_join(
            "grid_cell_i = :i AND grid_cell_j = :j",
            {"i": 2, "j": 3},
            limit=2,
        )
        assert len(rows) <= 2

    def test_cursor_excludes_earlier_patch_ids(self, seeded_preds, db_session):
        """cursor=N excludes all rows where patch_id <= N."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)

        all_rows = store._paginated_pred_join(
            "grid_cell_i = :i AND grid_cell_j = :j",
            {"i": 2, "j": 3},
        )
        assert len(all_rows) >= 2, "Need at least 2 rows to test cursor"

        first_patch_id = all_rows[0]["patch_id"]
        paged_rows = store._paginated_pred_join(
            "grid_cell_i = :i AND grid_cell_j = :j",
            {"i": 2, "j": 3},
            cursor=first_patch_id,
        )
        returned_ids = [r["patch_id"] for r in paged_rows]
        assert first_patch_id not in returned_ids
        assert all(pid > first_patch_id for pid in returned_ids)

    def test_results_ordered_by_patch_id(self, seeded_preds, db_session):
        """Rows are returned in ascending patch_id order."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store._paginated_pred_join(
            "grid_cell_i BETWEEN :i_min AND :i_max AND grid_cell_j BETWEEN :j_min AND :j_max",
            {"i_min": 0, "i_max": 10, "j_min": 0, "j_max": 10},
        )
        ids = [r["patch_id"] for r in rows]
        assert ids == sorted(ids)

    def test_include_image_true_returns_blob(self, seeded_preds, db_session):
        """include_image=True includes patch_image in results."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store._paginated_pred_join(
            "grid_cell_i = :i AND grid_cell_j = :j",
            {"i": 5, "j": 5},
            include_image=True,
        )
        assert len(rows) == 1
        assert "patch_image" in rows[0]
        assert isinstance(rows[0]["patch_image"], (bytes, memoryview))

    def test_include_image_false_excludes_blob(self, seeded_preds, db_session):
        """include_image=False omits patch_image from results."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store._paginated_pred_join(
            "grid_cell_i = :i AND grid_cell_j = :j",
            {"i": 5, "j": 5},
            include_image=False,
        )
        assert len(rows) == 1
        assert "patch_image" not in rows[0]

    def test_empty_result_when_no_pred_matches(self, seeded_preds, db_session):
        """Returns empty list when filter matches no rows in either pred table."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store._paginated_pred_join(
            "grid_cell_i = :i AND grid_cell_j = :j",
            {"i": 99, "j": 99},
        )
        assert rows == []

    def test_reserved_param_raises(self, seeded_preds, db_session):
        """Passing '_cursor' or '_limit' in pred_params raises ValueError."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        with pytest.raises(ValueError, match="_cursor"):
            store._paginated_pred_join(
                "grid_cell_i = :_cursor",
                {"_cursor": 0},
            )
        with pytest.raises(ValueError, match="_limit"):
            store._paginated_pred_join(
                "grid_cell_i = :i",
                {"i": 2, "_limit": 5},
            )

    def test_flat_dict_contains_expected_keys(self, seeded_preds, db_session):
        """Returned rows include both patch and pred columns."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store._paginated_pred_join(
            "grid_cell_i = :i AND grid_cell_j = :j",
            {"i": 5, "j": 5},
            include_image=False,
        )
        assert len(rows) == 1
        row = rows[0]
        # patch columns
        for key in ("patch_id", "patch_uid", "label_class_id", "image_id", "downsample_factor", "centroid_x", "centroid_y"):
            assert key in row, f"Expected patch column '{key}' in result"
        # pred columns
        for key in ("embed_x", "embed_y", "grid_cell_i", "grid_cell_j",
                    "pred_label_class_id", "event_ts", "priority"):
            assert key in row, f"Expected pred column '{key}' in result"


# ---------------------------------------------------------------------------
# get_patches_within_grid_bbox
# ---------------------------------------------------------------------------

class TestGetPatchesWithinGridBbox:
    BBOX = dict(i_min=2, i_max=3, j_min=3, j_max=4)

    def test_returns_in_bbox_patches(self, seeded_preds, db_session):
        """All four in-bbox patches are returned."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store.get_patches_within_grid_bbox(**self.BBOX)
        returned_ids = {r["patch_id"] for r in rows}
        assert returned_ids == seeded_preds["in_bbox_patch_ids"]

    def test_excludes_out_of_bbox_patches(self, seeded_preds, db_session):
        """Patch with pred outside bbox is not returned."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store.get_patches_within_grid_bbox(**self.BBOX)
        returned_ids = {r["patch_id"] for r in rows}
        for out_id in seeded_preds["out_of_bbox_patch_ids"]:
            assert out_id not in returned_ids

    def test_between_is_inclusive(self, seeded_preds, db_session):
        """The BETWEEN bounds are inclusive on both sides."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        # Exact equality on boundary: i_min==i_max==2, j_min==j_max==3
        rows = store.get_patches_within_grid_bbox(i_min=2, i_max=2, j_min=3, j_max=3)
        returned_ids = {r["patch_id"] for r in rows}
        p0, p3, p4 = (
            seeded_preds["patch_ids"][0],
            seeded_preds["patch_ids"][3],
            seeded_preds["patch_ids"][4],
        )
        assert p0 in returned_ids
        assert p3 in returned_ids
        assert p4 in returned_ids
        # p1 is at j=4, should not appear
        p1 = seeded_preds["patch_ids"][1]
        assert p1 not in returned_ids

    def test_cursor_pagination(self, seeded_preds, db_session):
        """Successive pages with cursor cover all in-bbox rows without overlap."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)

        page1 = store.get_patches_within_grid_bbox(**self.BBOX, limit=2)
        assert len(page1) == 2

        cursor = page1[-1]["patch_id"]
        page2 = store.get_patches_within_grid_bbox(**self.BBOX, cursor=cursor, limit=2)

        page1_ids = {r["patch_id"] for r in page1}
        page2_ids = {r["patch_id"] for r in page2}

        # No overlap
        assert page1_ids.isdisjoint(page2_ids)
        # Union covers all in-bbox patches
        assert page1_ids | page2_ids == seeded_preds["in_bbox_patch_ids"]

    def test_cursor_at_last_page_returns_empty(self, seeded_preds, db_session):
        """A cursor beyond the last patch_id yields an empty result."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)

        all_rows = store.get_patches_within_grid_bbox(**self.BBOX)
        last_cursor = max(r["patch_id"] for r in all_rows)
        rows = store.get_patches_within_grid_bbox(**self.BBOX, cursor=last_cursor)
        assert rows == []

    def test_include_image_default_true(self, seeded_preds, db_session):
        """patch_image is included by default."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store.get_patches_within_grid_bbox(**self.BBOX, limit=1)
        assert len(rows) == 1
        assert "patch_image" in rows[0]

    def test_include_image_false(self, seeded_preds, db_session):
        """include_image=False omits patch_image."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store.get_patches_within_grid_bbox(**self.BBOX, include_image=False)
        assert all("patch_image" not in r for r in rows)

    def test_empty_result_for_out_of_range_bbox(self, seeded_preds, db_session):
        """Returns empty list when bbox covers no seeded predictions."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store.get_patches_within_grid_bbox(
            i_min=50, i_max=60, j_min=50, j_max=60
        )
        assert rows == []

    def test_results_ordered_by_patch_id(self, seeded_preds, db_session):
        """Rows are in ascending patch_id order."""
        project_id = seeded_preds["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        rows = store.get_patches_within_grid_bbox(**self.BBOX)
        ids = [r["patch_id"] for r in rows]
        assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# Label-pair filtering
#
# Fixture layout (project_id=1, 5 patches from example_project):
#
#   patch | GT label  | pred table   | pred label | grid (i, j)
#   ------|-----------|--------------|------------|------------
#   p0    | tumor (0) | latest       | tumor (0)  | (2, 3)   ← concordant, in bbox
#   p1    | tumor (0) | latest       | normal (1) | (2, 4)   ← discordant, in bbox
#   p2    | normal(1) | latest       | tumor (0)  | (5, 5)   ← discordant, outside bbox
#   p3    | normal(1) | last only    | normal (1) | (2, 3)   ← concordant, in bbox
#   p4    | tumor (0) | latest+last  | tumor (0)  | (2, 3)   ← concordant, in bbox
#
# p2 and p3 have their GT label updated to "Normal" via update_label.
# Test bbox: i in [2,3], j in [3,4] → in-bbox patches: p0, p1, p3, p4
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_preds_lp(example_project: Dict[str, Any], db_session: Session) -> Dict[str, Any]:
    """Seed predictions with mixed (gt, pred) label-class combinations."""
    project_id: int = example_project["project"]["project_id"]
    tumor_id: int = example_project["label_classes"][0]["label_class_id"]
    normal_id: int = example_project["label_classes"][1]["label_class_id"]

    patch_ids = _get_patch_ids(db_session, project_id)
    assert len(patch_ids) == 5
    p0, p1, p2, p3, p4 = patch_ids

    store = PatchStore(project_id, db_session)

    # Clear existing predictions (distributed tables don't roll back properly)
    db_session.execute(text(f"DELETE FROM project{project_id}_pred_patch_latest"))
    db_session.execute(text(f"DELETE FROM project{project_id}_pred_patch_last"))
    db_session.flush()

    # Update GT labels for p2 and p3 to Normal
    store.update_label(p2, normal_id)
    store.update_label(p3, normal_id)

    # pred_patch_latest
    _insert_latest(
        db_session, project_id,
        [
            (p0, 0.10, 0.20, 2, 3, tumor_id),   # GT=tumor, pred=tumor, in bbox
            (p1, 0.11, 0.21, 2, 4, normal_id),  # GT=tumor, pred=normal, in bbox
            (p2, 0.12, 0.22, 5, 5, tumor_id),   # GT=normal, pred=tumor, outside bbox
            (p4, 0.14, 0.24, 2, 3, tumor_id),   # GT=tumor, pred=tumor, in bbox
        ],
    )

    # pred_patch_last
    _insert_last(
        db_session, project_id,
        [
            (p3, 0.30, 0.31, 2, 3, normal_id),  # GT=normal, pred=normal, in bbox (last only)
            (p4, 99.9, 99.9, 9, 9, normal_id),  # stale; latest wins for p4
        ],
    )

    db_session.flush()

    return {
        **example_project,
        "patch_ids": patch_ids,
        "tumor_id": tumor_id,
        "normal_id": normal_id,
        # Expected patch sets by (gt, pred) pair
        "tumor_tumor": {p0, p4},
        "tumor_normal": {p1},
        "normal_tumor": {p2},
        "normal_normal": {p3},
    }


class TestLabelPairsFilter:
    """Tests for label_pairs filtering in _paginated_pred_join, fetch_predicted,
    and get_patches_within_grid_bbox."""

    BBOX = dict(i_min=2, i_max=3, j_min=3, j_max=4)

    def test_single_concordant_pair(self, seeded_preds_lp, db_session):
        """label_pairs=[(tumor, tumor)] returns only concordant tumor patches."""
        project_id = seeded_preds_lp["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        tid = seeded_preds_lp["tumor_id"]

        rows = store.fetch_predicted(label_pairs=[(tid, tid)], include_image=False)
        returned_ids = {r["patch_id"] for r in rows}

        assert returned_ids == seeded_preds_lp["tumor_tumor"]

    def test_single_discordant_pair(self, seeded_preds_lp, db_session):
        """label_pairs=[(tumor, normal)] returns only the misclassified tumor patch."""
        project_id = seeded_preds_lp["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        tid = seeded_preds_lp["tumor_id"]
        nid = seeded_preds_lp["normal_id"]

        rows = store.fetch_predicted(label_pairs=[(tid, nid)], include_image=False)
        returned_ids = {r["patch_id"] for r in rows}

        assert returned_ids == seeded_preds_lp["tumor_normal"]

    def test_multiple_pairs_union(self, seeded_preds_lp, db_session):
        """Multiple pairs return the union of matching patches."""
        project_id = seeded_preds_lp["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        tid = seeded_preds_lp["tumor_id"]
        nid = seeded_preds_lp["normal_id"]

        rows = store.fetch_predicted(
            label_pairs=[(tid, tid), (tid, nid)],
            include_image=False,
        )
        returned_ids = {r["patch_id"] for r in rows}

        expected = seeded_preds_lp["tumor_tumor"] | seeded_preds_lp["tumor_normal"]
        assert returned_ids == expected

    def test_none_label_pairs_returns_all(self, seeded_preds_lp, db_session):
        """label_pairs=None applies no filter; all 5 patches are returned."""
        project_id = seeded_preds_lp["project"]["project_id"]
        store = PatchStore(project_id, db_session)

        rows = store.fetch_predicted(label_pairs=None, include_image=False)
        returned_ids = {r["patch_id"] for r in rows}

        all_ids = set(seeded_preds_lp["patch_ids"])
        assert returned_ids == all_ids

    def test_empty_list_returns_all(self, seeded_preds_lp, db_session):
        """label_pairs=[] (empty) is treated the same as None — no filtering."""
        project_id = seeded_preds_lp["project"]["project_id"]
        store = PatchStore(project_id, db_session)

        rows = store.fetch_predicted(label_pairs=[], include_image=False)
        returned_ids = {r["patch_id"] for r in rows}

        all_ids = set(seeded_preds_lp["patch_ids"])
        assert returned_ids == all_ids

    def test_no_matching_pair_returns_empty(self, seeded_preds_lp, db_session):
        """A pair that matches no patch yields an empty result."""
        project_id = seeded_preds_lp["project"]["project_id"]
        store = PatchStore(project_id, db_session)

        rows = store.fetch_predicted(label_pairs=[(99, 99)], include_image=False)
        assert rows == []

    def test_label_pairs_with_bbox_intersection(self, seeded_preds_lp, db_session):
        """get_patches_within_grid_bbox + label_pairs filters by both bbox and pair."""
        project_id = seeded_preds_lp["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        tid = seeded_preds_lp["tumor_id"]

        # In-bbox concordant tumor patches are p0 and p4; p2 (normal→tumor) is outside bbox
        rows = store.get_patches_within_grid_bbox(
            **self.BBOX,
            label_pairs=[(tid, tid)],
            include_image=False,
        )
        returned_ids = {r["patch_id"] for r in rows}

        assert returned_ids == seeded_preds_lp["tumor_tumor"]

    def test_label_pairs_bbox_no_match(self, seeded_preds_lp, db_session):
        """Bbox + pair that has no intersection returns empty."""
        project_id = seeded_preds_lp["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        tid = seeded_preds_lp["tumor_id"]
        nid = seeded_preds_lp["normal_id"]

        # normal→tumor pair: only p2 matches, which is outside the bbox
        rows = store.get_patches_within_grid_bbox(
            **self.BBOX,
            label_pairs=[(nid, tid)],
            include_image=False,
        )
        assert rows == []

    def test_gt_and_pred_label_class_id_values(self, seeded_preds_lp, db_session):
        """Verify label_class_id (GT) and pred_label_class_id are correctly returned."""
        project_id = seeded_preds_lp["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        tid = seeded_preds_lp["tumor_id"]
        nid = seeded_preds_lp["normal_id"]

        rows = store.fetch_predicted(label_pairs=[(tid, nid)], include_image=False)
        assert len(rows) == 1
        row = rows[0]
        assert row["label_class_id"] == tid,      "GT label should be tumor"
        assert row["pred_label_class_id"] == nid, "Pred label should be normal"

    def test_last_only_patch_included_in_pair_filter(self, seeded_preds_lp, db_session):
        """A patch with only a pred_patch_last row is returned when its pair matches."""
        project_id = seeded_preds_lp["project"]["project_id"]
        store = PatchStore(project_id, db_session)
        nid = seeded_preds_lp["normal_id"]
        p3 = seeded_preds_lp["patch_ids"][3]

        rows = store.fetch_predicted(label_pairs=[(nid, nid)], include_image=False)
        returned_ids = {r["patch_id"] for r in rows}

        assert p3 in returned_ids, "last-only patch p3 should be in (normal, normal) results"
