"""Tests for the upload session garbage collector."""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from patchsorter.api.v1.upload.gc import (
    _cleanup_abandoned_temp_dirs,
    _cleanup_expired_sessions,
)


# ------------------------------------------------------------------
# _cleanup_abandoned_temp_dirs
# ------------------------------------------------------------------


@pytest.fixture
def temp_base(tmp_path, monkeypatch):
    """Create a temp directory that mimics the system temp root."""
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    return tmp_path


def test_removes_orphaned_temp_dir(temp_base):
    """Orphaned ps_upload_* dirs are removed when no live actor exists."""
    session_id = "abc-123"
    abandoned = temp_base / f"ps_upload_{session_id}_xyz"
    abandoned.mkdir()
    (abandoned / "images").mkdir()
    (abandoned / "images" / "img.tif").write_text("data")

    live_session_ids = {"other-session"}

    _cleanup_abandoned_temp_dirs(live_session_ids)

    assert not abandoned.exists()


def test_preserves_active_temp_dir(temp_base):
    """Active ps_upload_* dirs are left alone when actor is live."""
    session_id = "def-456"
    active = temp_base / f"ps_upload_{session_id}_xyz"
    active.mkdir()
    (active / "images").mkdir()
    (active / "images" / "img.tif").write_text("data")

    live_session_ids = {session_id}

    _cleanup_abandoned_temp_dirs(live_session_ids)

    assert active.exists()
    assert (active / "images" / "img.tif").exists()


def test_skips_malformed_names(temp_base):
    """Dirs that don't parse as valid session IDs are skipped."""
    malformed = temp_base / "ps_upload__xyz"
    malformed.mkdir()

    live_session_ids = set()

    _cleanup_abandoned_temp_dirs(live_session_ids)

    assert malformed.exists()


def test_handles_missing_dirs(temp_base):
    """Race condition: dir disappears between listing and deletion."""
    session_id = "ghi-789"
    abandoned = temp_base / f"ps_upload_{session_id}_xyz"
    abandoned.mkdir()
    abandoned.rmdir()  # remove before cleanup runs

    live_session_ids = set()

    _cleanup_abandoned_temp_dirs(live_session_ids)


def test_handles_non_readable_dirs(temp_base, monkeypatch):
    """Errors during rmtree are caught and logged."""
    session_id = "jkl-012"
    abandoned = temp_base / f"ps_upload_{session_id}_xyz"
    abandoned.mkdir()

    live_session_ids = set()

    def fake_rmtree(path):
        raise PermissionError("denied")

    monkeypatch.setattr(shutil, "rmtree", fake_rmtree)

    _cleanup_abandoned_temp_dirs(live_session_ids)

    assert abandoned.exists()


def test_skips_non_directories(temp_base):
    """Non-directory entries matching the prefix are skipped."""
    fake_file = temp_base / "ps_upload_fakefile"
    fake_file.write_text("not a dir")

    live_session_ids = set()

    _cleanup_abandoned_temp_dirs(live_session_ids)

    assert fake_file.exists()


# ------------------------------------------------------------------
# _cleanup_expired_sessions
# ------------------------------------------------------------------


def test_noop_when_ray_unavailable(monkeypatch):
    """GC does nothing when ray is not available."""
    import patchsorter.api.v1.upload.gc as gc_module

    original_ray = gc_module.ray
    gc_module.ray = None

    try:
        _cleanup_expired_sessions(3600)
    finally:
        gc_module.ray = original_ray


def test_uses_single_list_actors_call(monkeypatch):
    """_cleanup_expired_sessions calls list_actors only once."""
    call_count = 0

    def fake_list_actors(**kwargs):
        nonlocal call_count
        call_count += 1
        return []

    monkeypatch.setattr(
        "patchsorter.api.v1.upload.gc.list_actors",
        fake_list_actors,
    )

    _cleanup_expired_sessions(3600)

    assert call_count == 1


def test_terminates_expired_actor(monkeypatch):
    """Expired actors are terminated."""
    session_id = "mno-345"
    now_ms = 1000 * 60 * 60 * 1000  # 100 hours ago in ms

    fake_actor = MagicMock()
    def fake_get(key, default=None):
        return {
            "name": f"upload_session_{session_id}",
            "start_time_ms": now_ms,
            "actor_id": "abc123",
        }.get(key, default)

    fake_actor.get = fake_get

    def fake_list_actors(**kwargs):
        return [fake_actor]

    terminate_called = []

    fake_handle = MagicMock()
    fake_terminate = MagicMock()
    fake_terminate.remote.return_value = MagicMock()
    fake_handle.__ray_terminate__ = fake_terminate

    def fake_get_actor(name):
        return fake_handle

    def fake_get(obj, **kwargs):
        terminate_called.append(True)

    monkeypatch.setattr(
        "patchsorter.api.v1.upload.gc.list_actors",
        fake_list_actors,
    )
    monkeypatch.setattr(
        "patchsorter.api.v1.upload.gc.ray.get_actor",
        fake_get_actor,
    )
    monkeypatch.setattr(
        "patchsorter.api.v1.upload.gc.ray.get",
        fake_get,
    )

    _cleanup_expired_sessions(3600)

    assert len(terminate_called) == 1
