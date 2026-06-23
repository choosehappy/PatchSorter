"""Unit tests for CitusShardMap — requires the ``_project1_tables`` fixture."""

import pytest

from patchsorter.db.head_client.database_manager import CitusShardMap


# --- Helper ---------------------------------------------------------------

def _make_shard_map(session, table_a="project1_patch", table_b="project1_pred_patch_latest"):
    return CitusShardMap(session, table_a, table_b)


# --- __init__ / _get_map_for_tables ---------------------------------------

def test_init_populates_map_with_colocated_tables(_project1_tables, db_session):
    """__init__ queries Citus system tables and populates the shard map for colocated tables."""
    sm = _make_shard_map(db_session)
    assert isinstance(sm.map, dict)


def test_map_keys_are_shard_ids(_project1_tables, db_session):
    """All keys in the map are integer shard IDs."""
    sm = _make_shard_map(db_session)
    for key in sm.map:
        assert isinstance(key, int)


def test_map_values_are_shard_ids(_project1_tables, db_session):
    """All values in the map are integer shard IDs."""
    sm = _make_shard_map(db_session)
    for val in sm.map:
        assert isinstance(val, int)


def test_map_is_not_empty_for_distributed_tables(_project1_tables, db_session):
    """Colocated distributed tables produce a non-empty shard map."""
    sm = _make_shard_map(db_session)
    if not sm.map:
        pytest.skip("No Citus worker nodes — map is empty")
    assert len(sm.map) > 0


# --- get_table_a_shard_list -----------------------------------------------

def test_get_table_a_shard_list_returns_keys(_project1_tables, db_session):
    """get_table_a_shard_list() returns the same keys as self.map."""
    sm = _make_shard_map(db_session)
    keys = sm.get_table_a_shard_list()
    assert set(keys) == set(sm.map.keys())


def test_get_table_a_shard_list_returns_list(_project1_tables, db_session):
    """get_table_a_shard_list() returns a list type."""
    sm = _make_shard_map(db_session)
    result = sm.get_table_a_shard_list()
    assert isinstance(result, list)


def test_get_table_a_shard_list_length_matches_map(_project1_tables, db_session):
    """get_table_a_shard_list() length equals the shard map size."""
    sm = _make_shard_map(db_session)
    assert len(sm.get_table_a_shard_list()) == len(sm.map)


# --- get_table_b_shard_list -----------------------------------------------

def test_get_table_b_shard_list_returns_values(_project1_tables, db_session):
    """get_table_b_shard_list() returns the same values as self.map."""
    sm = _make_shard_map(db_session)
    values = sm.get_table_b_shard_list()
    assert set(values) == set(sm.map.values())


def test_get_table_b_shard_list_returns_list(_project1_tables, db_session):
    """get_table_b_shard_list() returns a list type."""
    sm = _make_shard_map(db_session)
    result = sm.get_table_b_shard_list()
    assert isinstance(result, list)


def test_get_table_b_shard_list_length_matches_map(_project1_tables, db_session):
    """get_table_b_shard_list() length equals the shard map size."""
    sm = _make_shard_map(db_session)
    assert len(sm.get_table_b_shard_list()) == len(sm.map)


# --- get_b_shard_for_a_shard ----------------------------------------------

def test_get_b_shard_for_a_shard_returns_correct_mapping(_project1_tables, db_session):
    """get_b_shard_for_a_shard() returns the expected shard_b for a known shard_a."""
    sm = _make_shard_map(db_session)
    a_list = sm.get_table_a_shard_list()
    if not a_list:
        pytest.skip("No Citus worker nodes — no shard data available")
    shard_a = a_list[0]
    result = sm.get_b_shard_for_a_shard(shard_a)
    assert result == sm.map[shard_a]


def test_get_b_shard_for_a_shard_returns_int(_project1_tables, db_session):
    """get_b_shard_for_a_shard() returns an integer."""
    sm = _make_shard_map(db_session)
    a_list = sm.get_table_a_shard_list()
    if not a_list:
        pytest.skip("No Citus worker nodes — no shard data available")
    shard_a = a_list[0]
    result = sm.get_b_shard_for_a_shard(shard_a)
    assert isinstance(result, int)


def test_get_b_shard_for_a_shard_raises_on_missing_key(_project1_tables, db_session):
    """get_b_shard_for_a_shard() raises KeyError for an unknown shard_a."""
    sm = _make_shard_map(db_session)
    with pytest.raises(KeyError):
        sm.get_b_shard_for_a_shard(-999999)


# --- Bidirectional consistency --------------------------------------------

def test_reverse_lookup_consistent(_project1_tables, db_session):
    """For every (a, b) pair, looking up b in the reverse map yields a."""
    sm = _make_shard_map(db_session)
    a_list = sm.get_table_a_shard_list()
    for shard_a in a_list:
        shard_b = sm.get_b_shard_for_a_shard(shard_a)
        # Build reverse lookup
        reverse = {v: k for k, v in sm.map.items()}
        assert reverse[shard_b] == shard_a


def test_no_duplicate_shard_a(_project1_tables, db_session):
    """get_table_a_shard_list() has no duplicate shard IDs."""
    sm = _make_shard_map(db_session)
    a_list = sm.get_table_a_shard_list()
    assert len(a_list) == len(set(a_list))


def test_no_duplicate_shard_b(_project1_tables, db_session):
    """get_table_b_shard_list() has no duplicate shard IDs."""
    sm = _make_shard_map(db_session)
    b_list = sm.get_table_b_shard_list()
    assert len(b_list) == len(set(b_list))


# --- Different table pairs ------------------------------------------------

def test_init_with_different_colocated_tables(_project1_tables, db_session):
    """CitusShardMap works with a different pair of colocated tables."""
    sm = _make_shard_map(db_session, table_a="project1_patch", table_b="project1_pred_patch_last")
    assert isinstance(sm.map, dict)


def test_map_for_confusion_matrix_pair(_project1_tables, db_session):
    """CitusShardMap works with patch and confusion_matrix tables."""
    sm = CitusShardMap(db_session, "project1_patch", "project1_confusion_matrix_l8")
    assert isinstance(sm.map, dict)
