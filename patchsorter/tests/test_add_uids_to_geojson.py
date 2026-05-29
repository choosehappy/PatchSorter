"""Unit tests for add_uids() in patchsorter.helper_scripts.add_uuids_to_geojson."""

import json

import pytest
from osgeo import ogr

from patchsorter.helper_scripts.add_uuids_to_geojson import add_uids


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GEOJSON_TEMPLATE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            "properties": {"name": "a"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
            "properties": {"name": "b"},
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [2.0, 2.0]},
            "properties": {"name": "c"},
        },
    ],
}


def _write_geojson(path, data=None) -> None:
    """Write *data* (defaults to _GEOJSON_TEMPLATE) as a GeoJSON file at *path*."""
    path.write_text(json.dumps(data or _GEOJSON_TEMPLATE), encoding="utf-8")


def _read_features(path: str) -> list[dict]:
    """Return all features from a GeoJSON file as a list of property dicts."""
    ds = ogr.Open(str(path), 0)
    layer = ds.GetLayer(0)
    features = [json.loads(f.ExportToJson())["properties"] for f in layer]
    ds = None
    return features


def _field_names(path: str) -> set[str]:
    ds = ogr.Open(str(path), 0)
    layer = ds.GetLayer(0)
    defn = layer.GetLayerDefn()
    names = {defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())}
    ds = None
    return names


# ---------------------------------------------------------------------------
# In-place tests
# ---------------------------------------------------------------------------

def test_inplace_creates_uid_field(tmp_path):
    """uid field is created when it does not previously exist."""
    f = tmp_path / "test.geojson"
    _write_geojson(f)

    add_uids(str(f))

    assert "uid" in _field_names(str(f))


def test_inplace_all_features_have_uid(tmp_path):
    """Every feature receives a uid value after in-place modification."""
    f = tmp_path / "test.geojson"
    _write_geojson(f)

    add_uids(str(f))

    features = _read_features(str(f))
    assert len(features) == 3
    assert all(feat["uid"] is not None for feat in features)


def test_inplace_uid_values_are_valid_bigints(tmp_path):
    """Generated uid values are non-negative 63-bit integers."""
    f = tmp_path / "test.geojson"
    _write_geojson(f)

    add_uids(str(f))

    for feat in _read_features(str(f)):
        uid = feat["uid"]
        assert isinstance(uid, int)
        assert 0 <= uid < 2**63


def test_inplace_overwrites_existing_uid_field(tmp_path):
    """Calling add_uids twice produces new uid values (field already exists)."""
    f = tmp_path / "test.geojson"
    _write_geojson(f)

    add_uids(str(f))
    first_uids = [feat["uid"] for feat in _read_features(str(f))]

    add_uids(str(f))
    second_uids = [feat["uid"] for feat in _read_features(str(f))]

    # uid field must still be present
    assert "uid" in _field_names(str(f))
    # Values should change (probability of collision is astronomically low)
    assert first_uids != second_uids


def test_inplace_preserves_existing_properties(tmp_path):
    """In-place modification keeps all pre-existing feature properties intact."""
    f = tmp_path / "test.geojson"
    _write_geojson(f)

    add_uids(str(f))

    names = [feat["name"] for feat in _read_features(str(f))]
    assert names == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# New-file (output_path) tests
# ---------------------------------------------------------------------------

def test_output_path_creates_new_file(tmp_path):
    """Providing output_path creates the destination file."""
    src = tmp_path / "src.geojson"
    dst = tmp_path / "dst.geojson"
    _write_geojson(src)

    add_uids(str(src), str(dst))

    assert dst.exists()


def test_output_path_destination_has_uid_field(tmp_path):
    """The destination file has the uid field."""
    src = tmp_path / "src.geojson"
    dst = tmp_path / "dst.geojson"
    _write_geojson(src)

    add_uids(str(src), str(dst))

    assert "uid" in _field_names(str(dst))


def test_output_path_source_unchanged(tmp_path):
    """The source file is not modified when output_path is provided."""
    src = tmp_path / "src.geojson"
    dst = tmp_path / "dst.geojson"
    _write_geojson(src)
    original_text = src.read_text(encoding="utf-8")

    add_uids(str(src), str(dst))

    assert src.read_text(encoding="utf-8") == original_text


def test_output_path_all_features_present(tmp_path):
    """All features from the source appear in the output with valid uids."""
    src = tmp_path / "src.geojson"
    dst = tmp_path / "dst.geojson"
    _write_geojson(src)

    add_uids(str(src), str(dst))

    features = _read_features(str(dst))
    assert len(features) == 3
    assert all(0 <= feat["uid"] < 2**63 for feat in features)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_raises_for_missing_file(tmp_path):
    """RuntimeError is raised when the input file does not exist."""
    with pytest.raises(RuntimeError, match="OGR could not open"):
        add_uids(str(tmp_path / "nonexistent.geojson"))


def test_raises_for_invalid_output_dir(tmp_path):
    """RuntimeError is raised when the output directory does not exist."""
    src = tmp_path / "src.geojson"
    _write_geojson(src)

    with pytest.raises(RuntimeError, match="OGR could not create output"):
        add_uids(str(src), str(tmp_path / "no_such_dir" / "out.geojson"))
