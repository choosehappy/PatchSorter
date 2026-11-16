"""Unit tests for the local-shard-discovery query builders in ``db.utils``."""

from patchsorter.db.utils import (
    _LOCAL_SHARDS_SQL,
    _WORKER_FILTER,
    build_local_node_shards_query,
    build_local_worker_shards_query,
)


# --- build_local_node_shards_query -------------------------------------------

def test_local_node_query_contains_pg_dist_placement_join():
    assert "pg_dist_placement" in _LOCAL_SHARDS_SQL


def test_local_node_query_has_groupid_and_table_name_params():
    assert ":groupid" in _LOCAL_SHARDS_SQL
    assert ":table_name" in _LOCAL_SHARDS_SQL


def test_local_node_query_no_worker_filter_in_base():
    # Base SQL should not contain the worker filter.
    assert "WHERE rn" not in _LOCAL_SHARDS_SQL


def test_build_local_node_shards_query_binds_params():
    query = build_local_node_shards_query("project1_patch", groupid=5)
    bound = query.compile().params
    assert bound == {"table_name": "project1_patch", "groupid": 5}


# --- build_local_worker_shards_query ------------------------------------------

def test_worker_query_appends_worker_filter():
    combined = f"{_LOCAL_SHARDS_SQL.rstrip()}\n{_WORKER_FILTER}"
    assert "WHERE rn" in combined


def test_worker_filter_has_modulo_operator():
    assert "%" in _WORKER_FILTER
    assert ":num_workers" in _WORKER_FILTER
    assert ":current_worker_rank" in _WORKER_FILTER


def test_build_local_worker_shards_query_binds_params():
    query = build_local_worker_shards_query(
        "project1_patch", num_workers=4, current_worker_rank=2, groupid=5,
    )
    bound = query.compile().params
    assert bound == {
        "table_name": "project1_patch",
        "num_workers": 4,
        "current_worker_rank": 2,
        "groupid": 5,
    }
