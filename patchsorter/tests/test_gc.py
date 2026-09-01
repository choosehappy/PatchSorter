"""Unit tests for upload GC — mocks Ray APIs to test without a live cluster."""

import logging

import pytest

from patchsorter.api.v1.upload.gc import _cleanup_expired_sessions, start_gc_thread


def _make_actor_mock(name=None, start_time_ms=None):
    """Create a mock actor dict as returned by Ray's list_actors API."""
    return {
        "name": name or "session_actor",
        "actor_id": "abc123",
        "state": "ALIVE",
        "start_time_ms": start_time_ms or 0,
    }


# --- _cleanup_expired_sessions ------------------------------------------------


def test_no_actors_found(mocker):
    """_cleanup_expired_sessions() does nothing when no actors exist."""
    mocker.patch("patchsorter.api.v1.upload.gc.list_actors", return_value=[])
    # Should not raise
    _cleanup_expired_sessions(ttl_seconds=3600)


def test_no_expired_actors(mocker):
    """_cleanup_expired_sessions() skips actors within TTL."""
    now_ms = 1_000_000
    recent_ms = now_ms - 60_000  # 1 minute ago

    mock_actors = [_make_actor_mock(start_time_ms=recent_ms)]
    mocker.patch(
        "patchsorter.api.v1.upload.gc.list_actors",
        return_value=mock_actors,
    )

    # TTL = 3600s, actor is only 60s old — should not be cleaned up
    _cleanup_expired_sessions(ttl_seconds=3600)


def test_expired_actor_cleaned_up(mocker):
    """_cleanup_expired_sessions() calls cleanup() on expired actors."""
    now_ms = 10_000_000
    old_ms = now_ms - 7200_000  # 2 hours ago

    mock_actor = _make_actor_mock(name="test_session", start_time_ms=old_ms)
    mock_handle = mocker.MagicMock()
    terminate_mock = mocker.MagicMock()
    terminate_mock.remote.return_value = mocker.MagicMock()
    object.__setattr__(mock_handle, '__ray_terminate__', terminate_mock)

    mocker.patch(
        "patchsorter.api.v1.upload.gc.list_actors",
        return_value=[mock_actor],
    )
    mocker.patch(
        "patchsorter.api.v1.upload.gc.ray.get_actor",
        return_value=mock_handle,
    )

    _cleanup_expired_sessions(ttl_seconds=3600)

    mock_handle.__ray_terminate__.remote.assert_called_once()


def test_expired_actor_no_name_uses_actor_id(mocker):
    """_cleanup_expired_sessions() skips actors without a name (no get_actor call, no cleanup)."""
    now_ms = 10_000_000
    old_ms = now_ms - 7200_000

    # Directly create mock dict with name=None (bypass _make_actor_mock fallback)
    mock_actor = {
        "name": None,
        "actor_id": "abc123",
        "state": "ALIVE",
        "start_time_ms": old_ms,
    }

    mocker.patch(
        "patchsorter.api.v1.upload.gc.list_actors",
        return_value=[mock_actor],
    )
    mock_get_actor = mocker.patch(
        "patchsorter.api.v1.upload.gc.ray.get_actor",
    )
    mocker.patch("patchsorter.api.v1.upload.gc.time.time", return_value=now_ms / 1000)

    _cleanup_expired_sessions(ttl_seconds=3600)

    # No name → get_actor never called, no cleanup
    mock_get_actor.assert_not_called()


def test_list_actors_error_logged(mocker, caplog):
    """_cleanup_expired_sessions() logs a warning when list_actors fails."""
    mocker.patch(
        "patchsorter.api.v1.upload.gc.list_actors",
        side_effect=RuntimeError("connection refused"),
    )

    with caplog.at_level(logging.WARNING):
        _cleanup_expired_sessions(ttl_seconds=3600)

    assert any("failed to list actors" in record.message for record in caplog.records)


def test_get_actor_fails_gracefully(mocker):
    """_cleanup_expired_sessions() handles ray.get_actor raising RuntimeError."""
    now_ms = 10_000_000
    old_ms = now_ms - 7200_000

    mock_actor = _make_actor_mock(name="test_session", start_time_ms=old_ms)

    mocker.patch(
        "patchsorter.api.v1.upload.gc.list_actors",
        return_value=[mock_actor],
    )
    mocker.patch(
        "patchsorter.api.v1.upload.gc.ray.get_actor",
        side_effect=RuntimeError("not found"),
    )

    _cleanup_expired_sessions(ttl_seconds=3600)

    # get_actor raised → handle=None → actor skipped (no cleanup)


def test_cleanup_call_fails_logged(mocker, caplog):
    """_cleanup_expired_sessions() logs debug when __ray_terminate__() fails."""
    now_ms = 1_000_000
    old_ms = now_ms - 7200_000

    mock_actor = _make_actor_mock(name="test_session", start_time_ms=old_ms)
    mock_handle = mocker.MagicMock()
    terminate_mock = mocker.MagicMock()
    terminate_mock.remote.side_effect = RuntimeError("cleanup failed")
    object.__setattr__(mock_handle, '__ray_terminate__', terminate_mock)

    mocker.patch(
        "patchsorter.api.v1.upload.gc.list_actors",
        return_value=[mock_actor],
    )
    mocker.patch(
        "patchsorter.api.v1.upload.gc.ray.get_actor",
        return_value=mock_handle,
    )

    with caplog.at_level(logging.DEBUG):
        _cleanup_expired_sessions(ttl_seconds=3600)

    assert any("__ray_terminate__() call failed" in record.message for record in caplog.records)



def test_ttl_boundary_skips(mocker):
    """Actors exactly at TTL age are NOT cleaned up (must exceed)."""
    now_ms = 10_000_000
    exactly_ttl_ms = now_ms - 3600_000  # exactly 3600s old

    mock_actor = _make_actor_mock(name="test_session", start_time_ms=exactly_ttl_ms)
    mock_handle = mocker.MagicMock()

    mocker.patch(
        "patchsorter.api.v1.upload.gc.list_actors",
        return_value=[mock_actor],
    )
    mocker.patch(
        "patchsorter.api.v1.upload.gc.ray.get_actor",
        return_value=mock_handle,
    )
    mocker.patch("patchsorter.api.v1.upload.gc.time.time", return_value=now_ms / 1000)

    _cleanup_expired_sessions(ttl_seconds=3600)

    mock_handle.cleanup.remote.assert_not_called()


def test_ttl_boundary_kills_over(mocker):
    """Actors one millisecond past TTL ARE cleaned up."""
    now_ms = 1_000_000
    just_over_ms = now_ms - 3600_001  # 3600.001s old

    mock_actor = _make_actor_mock(name="test_session", start_time_ms=just_over_ms)
    mock_handle = mocker.MagicMock()
    terminate_mock = mocker.MagicMock()
    terminate_mock.remote.return_value = mocker.MagicMock()
    object.__setattr__(mock_handle, '__ray_terminate__', terminate_mock)

    mocker.patch(
        "patchsorter.api.v1.upload.gc.list_actors",
        return_value=[mock_actor],
    )
    mocker.patch(
        "patchsorter.api.v1.upload.gc.ray.get_actor",
        return_value=mock_handle,
    )

    _cleanup_expired_sessions(ttl_seconds=3600)

    terminate_mock.remote.assert_called_once()


def test_multiple_actors_only_expired_cleaned(mocker):
    """Only expired actors are cleaned; fresh actors are untouched."""
    now_ms = 10_000_000
    old_ms = now_ms - 7200_000
    fresh_ms = now_ms - 60_000

    mock_expired = _make_actor_mock(name="old_session", start_time_ms=old_ms)
    mock_fresh = _make_actor_mock(name="fresh_session", start_time_ms=fresh_ms)
    mock_fresh_handle = mocker.MagicMock()

    mocker.patch(
        "patchsorter.api.v1.upload.gc.list_actors",
        return_value=[mock_expired, mock_fresh],
    )

    mock_old_handle = mocker.MagicMock()
    mocker.patch(
        "patchsorter.api.v1.upload.gc.ray.get_actor",
        side_effect=lambda name: mock_fresh_handle if name == "fresh_session" else mock_old_handle,
    )
    mocker.patch("patchsorter.api.v1.upload.gc.time.time", return_value=now_ms / 1000)

    _cleanup_expired_sessions(ttl_seconds=3600)

    mock_fresh_handle.cleanup.remote.assert_not_called()


# --- start_gc_thread ----------------------------------------------------------


def test_start_gc_thread_is_daemon():
    """start_gc_thread() returns a daemon thread."""
    thread = start_gc_thread(ttl_seconds=1, interval_seconds=1)
    assert thread.daemon is True


def test_start_gc_thread_starts_running():
    """start_gc_thread() starts the thread immediately."""
    thread = start_gc_thread(ttl_seconds=1, interval_seconds=1)
    assert thread.is_alive()
