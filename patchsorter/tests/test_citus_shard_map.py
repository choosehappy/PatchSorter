"""Unit tests for ``CitusShardMap`` and shard query builders."""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from patchsorter.db.utils import CitusShardMap


# --- Test data helpers ------------------------------------------------------

def _make_row(shard_a: int, shard_b: int):
    return MagicMock(shard_a=shard_a, shard_b=shard_b)


SAMPLE_ROWS = [
    _make_row(100, 200),
    _make_row(101, 201),
    _make_row(102, 202),
]


# --- CitusShardMap.__init__ / from_rows ------------------------------------

def test_constructor_stores_rows_as_dataframe():
    sm = CitusShardMap(SAMPLE_ROWS)
    assert isinstance(sm.map, pd.DataFrame)
    assert list(sm.map.columns) == ["shard_a", "shard_b"]
    assert len(sm.map) == len(SAMPLE_ROWS)


def test_from_rows_produces_same_result():
    sm1 = CitusShardMap(SAMPLE_ROWS)
    sm2 = CitusShardMap.from_rows(SAMPLE_ROWS)
    pd.testing.assert_frame_equal(sm1.map, sm2.map)


def test_from_rows_with_empty_list():
    sm = CitusShardMap.from_rows([])
    assert len(sm.map) == 0


# --- get_table_a_shard_list -------------------------------------------------

def test_get_table_a_shard_list_returns_correct_values():
    sm = CitusShardMap(SAMPLE_ROWS)
    assert sm.get_table_a_shard_list() == [100, 101, 102]


def test_get_table_a_shard_list_returns_list():
    sm = CitusShardMap(SAMPLE_ROWS)
    result = sm.get_table_a_shard_list()
    assert isinstance(result, list)


def test_get_table_a_shard_list_empty_for_empty_input():
    sm = CitusShardMap.from_rows([])
    assert sm.get_table_a_shard_list() == []


# --- get_table_b_shard_list -------------------------------------------------

def test_get_table_b_shard_list_returns_correct_values():
    sm = CitusShardMap(SAMPLE_ROWS)
    assert sm.get_table_b_shard_list() == [200, 201, 202]


def test_get_table_b_shard_list_returns_list():
    sm = CitusShardMap(SAMPLE_ROWS)
    result = sm.get_table_b_shard_list()
    assert isinstance(result, list)


def test_get_table_b_shard_list_empty_for_empty_input():
    sm = CitusShardMap.from_rows([])
    assert sm.get_table_b_shard_list() == []


# --- get_b_shard_for_a_shard ------------------------------------------------

def test_get_b_shard_for_a_shard_returns_correct_mapping():
    sm = CitusShardMap(SAMPLE_ROWS)
    assert sm.get_b_shard_for_a_shard(100) == 200
    assert sm.get_b_shard_for_a_shard(101) == 201
    assert sm.get_b_shard_for_a_shard(102) == 202


def test_get_b_shard_for_a_shard_returns_int():
    sm = CitusShardMap(SAMPLE_ROWS)
    result = sm.get_b_shard_for_a_shard(100)
    assert isinstance(result, int)


def test_get_b_shard_for_a_shard_raises_on_missing_key():
    sm = CitusShardMap(SAMPLE_ROWS)
    with pytest.raises(KeyError, match="shard_a=9999 not found"):
        sm.get_b_shard_for_a_shard(9999)


def test_get_b_shard_for_a_shard_empty_map_raises():
    sm = CitusShardMap.from_rows([])
    with pytest.raises(KeyError):
        sm.get_b_shard_for_a_shard(1)


# --- get_a_shard_for_b_shard ------------------------------------------------

def test_get_a_shard_for_b_shard_returns_correct_mapping():
    sm = CitusShardMap(SAMPLE_ROWS)
    assert sm.get_a_shard_for_b_shard(200) == 100
    assert sm.get_a_shard_for_b_shard(201) == 101
    assert sm.get_a_shard_for_b_shard(202) == 102


def test_get_a_shard_for_b_shard_returns_int():
    sm = CitusShardMap(SAMPLE_ROWS)
    result = sm.get_a_shard_for_b_shard(200)
    assert isinstance(result, int)


def test_get_a_shard_for_b_shard_raises_on_missing_key():
    sm = CitusShardMap(SAMPLE_ROWS)
    with pytest.raises(KeyError, match="shard_b=9999 not found"):
        sm.get_a_shard_for_b_shard(9999)


def test_get_a_shard_for_b_shard_empty_map_raises():
    sm = CitusShardMap.from_rows([])
    with pytest.raises(KeyError):
        sm.get_a_shard_for_b_shard(1)


# --- Bidirectional consistency ----------------------------------------------

def test_bidirectional_lookup_consistency():
    sm = CitusShardMap(SAMPLE_ROWS)
    for shard_a in sm.get_table_a_shard_list():
        shard_b = sm.get_b_shard_for_a_shard(shard_a)
        assert sm.get_a_shard_for_b_shard(shard_b) == shard_a


def test_no_duplicate_shard_a():
    sm = CitusShardMap(SAMPLE_ROWS)
    a_list = sm.get_table_a_shard_list()
    assert len(a_list) == len(set(a_list))


def test_no_duplicate_shard_b():
    sm = CitusShardMap(SAMPLE_ROWS)
    b_list = sm.get_table_b_shard_list()
    assert len(b_list) == len(set(b_list))


# --- build_local_node_shard_map_query ---------------------------------------

def test_local_node_query_contains_pg_dist_placement_joins():
    from patchsorter.db.utils import _SHARD_MAP_SQL
    assert "pg_dist_placement" in _SHARD_MAP_SQL


def test_local_node_query_has_groupid_param():
    from patchsorter.db.utils import _SHARD_MAP_SQL
    assert ":groupid" in _SHARD_MAP_SQL


def test_local_node_query_no_worker_filter_in_base():
    from patchsorter.db.utils import _SHARD_MAP_SQL
    # Base SQL should not contain the worker filter
    assert "WHERE rn" not in _SHARD_MAP_SQL


# --- build_local_worker_shard_map_query -------------------------------------

def test_worker_query_appends_worker_filter():
    from patchsorter.db.utils import _SHARD_MAP_SQL, _WORKER_FILTER
    combined = f"{_SHARD_MAP_SQL.rstrip()}\n{_WORKER_FILTER}"
    assert "WHERE rn" in combined


def test_worker_filter_has_modulo_operator():
    from patchsorter.db.utils import _WORKER_FILTER
    assert "%" in _WORKER_FILTER
    assert ":num_workers" in _WORKER_FILTER
    assert ":current_worker_rank" in _WORKER_FILTER
