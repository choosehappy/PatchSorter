"""ConfusionMatrixStore must give correct results for a partial label subset."""

import numpy as np

from patchsorter.db.head_client.confusion_matrix import ConfusionMatrixStore


def _store(raw: np.ndarray) -> ConfusionMatrixStore:
    store = object.__new__(ConfusionMatrixStore)
    store.bbox_search = lambda bbox, label_pairs: raw
    return store


def test_partial_label_subset_counts_land_in_correct_cells():
    # True labels are [-1, 1, 2, 3, 4, 5], but only classes 3 and 4 are requested.
    pairs = [(3, 3), (3, 4), (4, 3), (4, 4)]
    # rows: gt, pred, i, j, count
    raw = np.array(
        [
            [3, 3, 0, 0, 5],
            [3, 4, 0, 1, 2],
            [4, 3, 1, 0, 7],
            [4, 4, 1, 1, 11],
        ],
        dtype=np.int64,
    )
    confusion, gt, pred = _store(raw).read_confusion_matrix((0, 0, 1, 1), pairs)

    assert gt.tolist() == [3, 4]
    assert pred.tolist() == [3, 4]
    assert confusion.tolist() == [[5, 2], [7, 11]]


def test_read_region_with_unassigned_in_subset():
    pairs = [(-1, 2), (2, 2)]
    raw = np.array([[-1, 2, 0, 0, 4], [2, 2, 0, 0, 6]], dtype=np.int64)
    region, classes = _store(raw).read_region((0, 0, 0, 0), pairs, sum_over_gt=True)

    assert classes.tolist() == [2]
    assert region[0, 0, 0] == 10
