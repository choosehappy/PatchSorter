"""Unit tests for :class:`~patchsorter.dl.training.LabelMap`."""

import pytest

from patchsorter.db.head_client.models import LabelClass
from patchsorter.dl.training import LabelMap
from patchsorter.config.constants import UNASSIGNED_LABEL_CLASS_ID


def _make_label_class(label_class_id: int, name: str = "Class", project_id: int = 1) -> LabelClass:
    """Helper to create a :class:`~patchsorter.db.head_client.models.LabelClass` stub."""
    lc = LabelClass()
    lc.label_class_id = label_class_id
    lc.name = name
    lc.project_id = project_id
    return lc


class TestLabelMapNClasses:
    def test_get_n_classes_excludes_unassigned(self):
        """get_n_classes() excludes the unassigned class (id=-1) from the count."""
        classes = [
            _make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned"),
            _make_label_class(1, "Tumor"),
            _make_label_class(3, "Normal"),
        ]
        lm = LabelMap(classes)
        assert lm.get_n_classes() == 2

    def test_get_n_classes_empty(self):
        """get_n_classes() returns 0 when no valid classes exist."""
        classes = [_make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned")]
        lm = LabelMap(classes)
        assert lm.get_n_classes() == 0

    def test_get_n_classes_only_unassigned(self):
        """get_n_classes() returns 0 when only the unassigned class is present."""
        classes = [_make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned")]
        lm = LabelMap(classes)
        assert lm.get_n_classes() == 0

    def test_get_n_classes_multiple_valid(self):
        """get_n_classes() counts all non-unassigned classes."""
        classes = [
            _make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned"),
            _make_label_class(1, "Tumor"),
            _make_label_class(3, "Normal"),
            _make_label_class(5, "Stroma"),
        ]
        lm = LabelMap(classes)
        assert lm.get_n_classes() == 3


class TestLabelMapToModelIndex:
    def test_maps_valid_class_ids(self):
        """to_model_index() maps valid DB IDs to sequential model indices."""
        classes = [
            _make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned"),
            _make_label_class(3, "Tumor"),
            _make_label_class(1, "Normal"),
        ]
        lm = LabelMap(classes)
        assert lm.to_model_index(1) == 0  # sorted: 1->0, 3->1
        assert lm.to_model_index(3) == 1

    def test_to_model_index_unassigned_returns_minus_one(self):
        """to_model_index() returns -1 for the unassigned class (id=-1)."""
        classes = [
            _make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned"),
            _make_label_class(1, "Tumor"),
        ]
        lm = LabelMap(classes)
        assert lm.to_model_index(UNASSIGNED_LABEL_CLASS_ID) == -1

    def test_to_model_index_none_returns_minus_one(self):
        """to_model_index() returns -1 for None input."""
        classes = [_make_label_class(1, "Tumor")]
        lm = LabelMap(classes)
        assert lm.to_model_index(None) == -1

    def test_to_model_index_unknown_id_returns_minus_one(self):
        """to_model_index() returns -1 for IDs not in the mapping."""
        classes = [_make_label_class(1, "Tumor")]
        lm = LabelMap(classes)
        assert lm.to_model_index(99) == -1

    def test_mapping_is_deterministic_and_sorted(self):
        """to_model_index() produces consistent ordering regardless of input order."""
        classes_a = [
            _make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned"),
            _make_label_class(7, "Z"),
            _make_label_class(1, "A"),
            _make_label_class(3, "B"),
        ]
        classes_b = [
            _make_label_class(3, "B"),
            _make_label_class(1, "A"),
            _make_label_class(7, "Z"),
            _make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned"),
        ]
        lm_a = LabelMap(classes_a)
        lm_b = LabelMap(classes_b)
        assert lm_a.to_model_index(1) == lm_b.to_model_index(1)
        assert lm_a.to_model_index(3) == lm_b.to_model_index(3)
        assert lm_a.to_model_index(7) == lm_b.to_model_index(7)


class TestLabelMapFromModelIndex:
    def test_maps_model_indices_to_class_ids(self):
        """from_model_index() maps model indices back to DB class IDs."""
        classes = [
            _make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned"),
            _make_label_class(3, "Tumor"),
            _make_label_class(1, "Normal"),
        ]
        lm = LabelMap(classes)
        assert lm.from_model_index(0) == 1
        assert lm.from_model_index(1) == 3

    def test_from_model_index_out_of_range_raises(self):
        """from_model_index() raises ValueError for out-of-range indices."""
        classes = [
            _make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned"),
            _make_label_class(1, "Tumor"),
        ]
        lm = LabelMap(classes)
        with pytest.raises(ValueError, match="model_idx -1 is out of range"):
            lm.from_model_index(-1)
        with pytest.raises(ValueError, match="model_idx 999 is out of range"):
            lm.from_model_index(999)

    def test_from_model_index_with_no_valid_classes_raises(self):
        """from_model_index() raises ValueError when no valid classes exist."""
        classes = [_make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned")]
        lm = LabelMap(classes)
        with pytest.raises(ValueError, match="model_idx 0 is out of range"):
            lm.from_model_index(0)


class TestLabelMapRoundTrip:
    def test_round_trip_to_from(self):
        """to_model_index -> from_model_index recovers the original valid DB ID."""
        classes = [
            _make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned"),
            _make_label_class(5, "Tumor"),
            _make_label_class(1, "Normal"),
            _make_label_class(7, "Stroma"),
        ]
        lm = LabelMap(classes)
        for db_id in [1, 5, 7]:
            idx = lm.to_model_index(db_id)
            assert idx >= 0
            assert lm.from_model_index(idx) == db_id

    def test_round_trip_unassigned_preserves_minus_one(self):
        """Unassigned (id=-1) stays -1 through the round-trip."""
        classes = [_make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned"), _make_label_class(1, "Tumor")]
        lm = LabelMap(classes)
        idx = lm.to_model_index(UNASSIGNED_LABEL_CLASS_ID)
        assert idx == -1
        with pytest.raises(ValueError):
            lm.from_model_index(idx)

    def test_round_trip_none_preserves_minus_one(self):
        """None input stays -1 through the round-trip."""
        classes = [_make_label_class(1, "Tumor")]
        lm = LabelMap(classes)
        idx = lm.to_model_index(None)
        assert idx == -1
        with pytest.raises(ValueError):
            lm.from_model_index(idx)

    def test_unassigned_never_predicted(self):
        """The unassigned class (id=-1) cannot appear as a predicted class."""
        classes = [
            _make_label_class(UNASSIGNED_LABEL_CLASS_ID, "Unassigned"),
            _make_label_class(1, "Tumor"),
            _make_label_class(3, "Normal"),
        ]
        lm = LabelMap(classes)
        n = lm.get_n_classes()
        # All valid model indices map back to non-unassigned DB IDs
        for i in range(n):
            assert lm.from_model_index(i) != UNASSIGNED_LABEL_CLASS_ID
