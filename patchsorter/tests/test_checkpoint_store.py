"""Unit tests for checkpoint path resolution and save/load utilities."""

import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import torch
from safetensors.torch import load_file

from patchsorter.config.constants import CheckpointModuleType
from patchsorter.dl.training import load_checkpoint, save_checkpoint
from patchsorter.utils.fsmanager import NASWriteStore


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def nas_write(tmp_path, monkeypatch):
    """Create a NASWriteStore pointing at *tmp_path*."""
    monkeypatch.setattr(
        "patchsorter.config.constants.MOUNTS_PATH", str(tmp_path)
    )
    return NASWriteStore()


@pytest.fixture
def fake_model():
    """Return a minimal mock model with a state_dict."""
    model = MagicMock()
    model.state_dict.return_value = {
        "weight": MagicMock(),
        "bias": MagicMock(),
    }
    return model


# ------------------------------------------------------------------
# get_checkpoint_dir
# ------------------------------------------------------------------


def test_get_checkpoint_dir_creates_directory(nas_write, tmp_path):
    """get_checkpoint_dir creates the checkpoints directory if it does not exist."""
    project_id = 42
    result = nas_write.get_checkpoint_dir(project_id)
    expected = tmp_path / "nas_write" / "projects" / f"proj_{project_id}" / "checkpoints"
    assert result == expected
    assert result.is_dir()


def test_get_checkpoint_dir_returns_same_path_on_repeated_call(nas_write, tmp_path):
    """Repeated calls to get_checkpoint_dir return the same Path."""
    project_id = 42
    first = nas_write.get_checkpoint_dir(project_id)
    second = nas_write.get_checkpoint_dir(project_id)
    assert first == second


# ------------------------------------------------------------------
# get_latest_checkpoint_dir
# ------------------------------------------------------------------


def test_get_latest_checkpoint_dir_returns_none_when_no_checkpoints(nas_write):
    """get_latest_checkpoint_dir returns None when no checkpoints exist."""
    nas_write.get_checkpoint_dir(1)  # create the base checkpoints dir
    assert nas_write.get_latest_checkpoint_dir(1) is None


def test_get_latest_checkpoint_dir_returns_newest_dir(nas_write):
    """get_latest_checkpoint_dir returns the newest checkpoint directory."""
    project_id = 1
    base = nas_write.get_checkpoint_dir(project_id)
    (base / "20260101_10-00-00").mkdir()
    (base / "20260102_12-30-00").mkdir()
    (base / "20260103_08-15-00").mkdir()

    result = nas_write.get_latest_checkpoint_dir(project_id)
    assert result == base / "20260103_08-15-00"


def test_get_latest_checkpoint_dir_skips_non_directories(nas_write):
    """get_latest_checkpoint_dir ignores non-directory entries."""
    project_id = 1
    base = nas_write.get_checkpoint_dir(project_id)
    (base / "20260101_10-00-00").mkdir()
    (base / "20260102_10-00-00").mkdir()
    (base / "fake_file").write_text("not a dir")

    result = nas_write.get_latest_checkpoint_dir(project_id)
    assert result.name == "20260102_10-00-00"


# ------------------------------------------------------------------
# get_all_checkpoint_dirs
# ------------------------------------------------------------------


def test_get_all_checkpoint_dirs_returns_empty_list_when_none_exist(nas_write):
    """get_all_checkpoint_dirs returns an empty list when no checkpoints exist."""
    nas_write.get_checkpoint_dir(1)
    assert nas_write.get_all_checkpoint_dirs(1) == []


def test_get_all_checkpoint_dirs_returns_sorted_dirs(nas_write):
    """get_all_checkpoint_dirs returns directories sorted newest-first."""
    project_id = 1
    base = nas_write.get_checkpoint_dir(project_id)
    for ts in ["20260101_10-00-00", "20260103_08-00-00", "20260102_12-00-00"]:
        (base / ts).mkdir()

    result = nas_write.get_all_checkpoint_dirs(project_id)
    assert len(result) == 3
    assert result[0].name == "20260103_08-00-00"
    assert result[1].name == "20260102_12-00-00"
    assert result[2].name == "20260101_10-00-00"


# ------------------------------------------------------------------
# get_checkpoint_dir_by_name
# ------------------------------------------------------------------


def test_get_checkpoint_dir_by_name_returns_path_when_exists(nas_write):
    """get_checkpoint_dir_by_name returns the full path when the directory exists."""
    project_id = 1
    checkpoint_name = "20260101_10-00-00"
    nas_write.get_checkpoint_dir(project_id)
    (nas_write.get_checkpoint_dir(project_id) / checkpoint_name).mkdir()

    result = nas_write.get_checkpoint_dir_by_name(project_id, checkpoint_name)
    assert result is not None
    assert result.name == checkpoint_name
    assert result.is_dir()


def test_get_checkpoint_dir_by_name_returns_none_when_missing(nas_write):
    """get_checkpoint_dir_by_name returns None when the directory does not exist."""
    nas_write.get_checkpoint_dir(1)
    assert nas_write.get_checkpoint_dir_by_name(1, "20260101_10-00-00") is None


# ------------------------------------------------------------------
# get_new_checkpoint_dir_path
# ------------------------------------------------------------------


def test_get_new_checkpoint_dir_path_returns_new_timestamp_path(nas_write):
    """get_new_checkpoint_dir_path returns a path with a new timestamp."""
    project_id = 1
    result = nas_write.get_new_checkpoint_dir_path(project_id)

    assert "checkpoints" in str(result)
    assert result.name != "checkpoints"
    assert not result.exists()


def test_get_new_checkpoint_dir_path_creates_unique_paths(monkeypatch, nas_write):
    """Consecutive calls to get_new_checkpoint_dir_path return different paths."""
    project_id = 1
    nas_write.get_checkpoint_dir(project_id)

    counter = [0]

    def fake_strftime(fmt):
        counter[0] += 1
        return f"20260101_10-00-{counter[0]:02d}"

    with patch("patchsorter.utils.fsmanager.datetime.datetime") as MockDatetime:
        mock_now = MagicMock()
        mock_now.strftime = MagicMock(side_effect=fake_strftime)
        MockDatetime.now.return_value = mock_now

        first = nas_write.get_new_checkpoint_dir_path(project_id)
        second = nas_write.get_new_checkpoint_dir_path(project_id)
        assert first != second


# ------------------------------------------------------------------
# truncate_checkpoints
# ------------------------------------------------------------------


def test_truncate_checkpoints_noop_when_under_limit(nas_write):
    """truncate_checkpoints does nothing when under the default limit."""
    project_id = 1
    base = nas_write.get_checkpoint_dir(project_id)
    for i in range(3):
        (base / f"2026010{i + 1}_10-00-00").mkdir()

    nas_write.truncate_checkpoints(project_id, max_checkpoints=5)

    assert len(nas_write.get_all_checkpoint_dirs(project_id)) == 3


def test_truncate_checkpoints_removes_excess_dirs(nas_write):
    """truncate_checkpoints removes directories exceeding the limit."""
    project_id = 1
    base = nas_write.get_checkpoint_dir(project_id)
    for i in range(7):
        (base / f"2026010{i + 1}_10-00-00").mkdir()

    nas_write.truncate_checkpoints(project_id, max_checkpoints=3)

    remaining = nas_write.get_all_checkpoint_dirs(project_id)
    assert len(remaining) == 3
    assert remaining[0].name == "20260107_10-00-00"


def test_truncate_checkpoints_custom_limit(nas_write):
    """truncate_checkpoints respects a custom max_checkpoints value."""
    project_id = 1
    base = nas_write.get_checkpoint_dir(project_id)
    for i in range(5):
        (base / f"2026010{i + 1}_10-00-00").mkdir()

    nas_write.truncate_checkpoints(project_id, max_checkpoints=2)

    remaining = nas_write.get_all_checkpoint_dirs(project_id)
    assert len(remaining) == 2


def test_truncate_checkpoints_no_checkpoint_dir(nas_write):
    """truncate_checkpoints does not raise when no checkpoint dir exists."""
    nas_write.truncate_checkpoints(999, max_checkpoints=5)


# ------------------------------------------------------------------
# get_checkpoint_path
# ------------------------------------------------------------------


def test_get_checkpoint_path_backbone(nas_write):
    """get_checkpoint_path returns the correct path for backbone."""
    project_id = 1
    checkpoint_dir = nas_write.get_checkpoint_dir(project_id) / "20260101_10-00-00"
    checkpoint_dir.mkdir(parents=True)

    result = nas_write.get_checkpoint_path(project_id, CheckpointModuleType.BACKBONE, checkpoint_dir)
    assert result == checkpoint_dir / "backbone.safetensors"


def test_get_checkpoint_path_head(nas_write):
    """get_checkpoint_path returns the correct path for head."""
    project_id = 1
    checkpoint_dir = nas_write.get_checkpoint_dir(project_id) / "20260101_10-00-00"
    checkpoint_dir.mkdir(parents=True)

    result = nas_write.get_checkpoint_path(project_id, CheckpointModuleType.HEAD, checkpoint_dir)
    assert result == checkpoint_dir / "head.safetensors"


# ------------------------------------------------------------------
# get_latest_checkpoint_path
# ------------------------------------------------------------------


def test_get_latest_checkpoint_path_returns_none_when_no_checkpoints(nas_write):
    """get_latest_checkpoint_path returns None when no checkpoints exist."""
    nas_write.get_checkpoint_dir(1)
    assert nas_write.get_latest_checkpoint_path(1, CheckpointModuleType.BACKBONE) is None


def test_get_latest_checkpoint_path_returns_path_when_exists(nas_write):
    """get_latest_checkpoint_path returns the path when a checkpoint exists."""
    project_id = 1
    base = nas_write.get_checkpoint_dir(project_id)
    ckpt_dir = base / "20260101_10-00-00"
    ckpt_dir.mkdir()
    (ckpt_dir / "backbone.safetensors").write_bytes(b"")
    (ckpt_dir / "head.safetensors").write_bytes(b"")

    backbone_path = nas_write.get_latest_checkpoint_path(project_id, CheckpointModuleType.BACKBONE)
    head_path = nas_write.get_latest_checkpoint_path(project_id, CheckpointModuleType.HEAD)

    assert backbone_path == ckpt_dir / "backbone.safetensors"
    assert head_path == ckpt_dir / "head.safetensors"


# ------------------------------------------------------------------
# load_checkpoint / save_checkpoint (training.py utilities)
# ------------------------------------------------------------------


def _make_model():
    return torch.nn.Linear(3, 2)


def test_load_checkpoint_raises_when_no_checkpoints(nas_write):
    """load_checkpoint raises FileNotFoundError when no checkpoints exist."""
    nas_write.get_checkpoint_dir(1)
    with pytest.raises(FileNotFoundError):
        load_checkpoint(1, _make_model(), CheckpointModuleType.BACKBONE)


def test_load_checkpoint_raises_when_specific_dir_missing(nas_write):
    """load_checkpoint raises FileNotFoundError when the given directory does not exist."""
    nas_write.get_checkpoint_dir(1)
    with pytest.raises(FileNotFoundError):
        load_checkpoint(1, _make_model(), CheckpointModuleType.BACKBONE, checkpoint_dir=Path("/nonexistent"))


def test_save_checkpoint_creates_new_dir_and_file(nas_write):
    """save_checkpoint with no directory creates a new one and returns the file path."""
    nas_write.get_checkpoint_dir(1)
    path = save_checkpoint(1, _make_model(), CheckpointModuleType.BACKBONE)

    assert path.is_file()
    assert path.name == "backbone.safetensors"
    assert path.parent.parent == nas_write.get_checkpoint_dir(1)


def test_save_checkpoint_uses_given_dir(nas_write):
    """save_checkpoint writes into the provided directory, one file per type."""
    ckpt_dir = nas_write.get_checkpoint_dir(1) / "20260101_10-00-00"
    ckpt_dir.mkdir()

    backbone_path = save_checkpoint(1, _make_model(), CheckpointModuleType.BACKBONE, ckpt_dir)
    head_path = save_checkpoint(1, _make_model(), CheckpointModuleType.HEAD, ckpt_dir)

    assert backbone_path == ckpt_dir / "backbone.safetensors"
    assert head_path == ckpt_dir / "head.safetensors"
    assert backbone_path.exists() and head_path.exists()


def test_save_checkpoint_keys_are_unprefixed(nas_write):
    """Saved state_dict keys match the model's own keys."""
    path = save_checkpoint(1, _make_model(), CheckpointModuleType.HEAD)
    assert set(load_file(str(path))) == {"weight", "bias"}


def test_checkpoint_roundtrip_latest(nas_write):
    """Weights saved by save_checkpoint are restored by load_checkpoint."""
    source, target = _make_model(), _make_model()
    save_checkpoint(1, source, CheckpointModuleType.BACKBONE)

    load_checkpoint(1, target, CheckpointModuleType.BACKBONE)

    assert torch.equal(source.weight, target.weight)
    assert torch.equal(source.bias, target.bias)


def test_checkpoint_roundtrip_specific_dir(nas_write):
    """load_checkpoint restores from an explicitly given directory."""
    ckpt_dir = nas_write.get_checkpoint_dir(1) / "20260101_10-00-00"
    ckpt_dir.mkdir()
    source, target = _make_model(), _make_model()
    save_checkpoint(1, source, CheckpointModuleType.HEAD, ckpt_dir)

    load_checkpoint(1, target, CheckpointModuleType.HEAD, checkpoint_dir=ckpt_dir)

    assert torch.equal(source.weight, target.weight)


def test_checkpoint_roundtrip_ddp_wrapped(nas_write):
    """Both functions unwrap DDP-style models via ``.module``."""
    class Wrapper(torch.nn.Module):
        def __init__(self, module):
            super().__init__()
            self.module = module

    source, target = _make_model(), _make_model()
    save_checkpoint(1, Wrapper(source), CheckpointModuleType.BACKBONE)
    load_checkpoint(1, Wrapper(target), CheckpointModuleType.BACKBONE)

    assert torch.equal(source.weight, target.weight)


def test_load_checkpoint_raises_on_key_mismatch(nas_write):
    """A checkpoint whose keys do not match the model is rejected."""
    save_checkpoint(1, torch.nn.Linear(3, 2), CheckpointModuleType.BACKBONE)
    other = torch.nn.Sequential(torch.nn.Linear(3, 2))
    with pytest.raises(RuntimeError):
        load_checkpoint(1, other, CheckpointModuleType.BACKBONE)
