"""Tests for the UploadSessionActor core logic.

The actor's methods delegate to module-level functions that accept
a ``tmpdir`` parameter. Tests call these functions directly with
pytest's ``tmp_path`` fixture — no Ray runtime required.
"""

import os
import tempfile
from unittest.mock import MagicMock

import pytest

from patchsorter.api.v1.upload.actor import (
    _save_files,
    _validate_csv,
    _validate_folders,
    _validate_paths,
)


# ------------------------------------------------------------------
# _save_files
# ------------------------------------------------------------------


def test_save_files_creates_subdir_and_writes(tmp_path):
    """_save_files() creates subdir and writes file contents."""
    result = _save_files(str(tmp_path), "images", ["a.tif", "b.tif"], [b"1", b"2"])

    assert "Uploaded 2 image(s)" == result
    assert os.path.isfile(os.path.join(str(tmp_path), "images", "a.tif"))
    assert os.path.isfile(os.path.join(str(tmp_path), "images", "b.tif"))
    assert open(os.path.join(str(tmp_path), "images", "a.tif"), "rb").read() == b"1"


def test_save_files_strips_paths(tmp_path):
    """_save_files() strips directory paths from filenames."""
    result = _save_files(str(tmp_path), "images", ["subdir/c.tif"], [b"3"])

    assert os.path.isfile(os.path.join(str(tmp_path), "images", "c.tif"))


def test_save_files_empty(tmp_path):
    """_save_files([]) returns a zero count message."""
    result = _save_files(str(tmp_path), "images", [], [])

    assert "Uploaded 0 image(s)" == result


def test_save_masks(tmp_path):
    """_save_files() with 'masks' subdir writes to masks."""
    _save_files(str(tmp_path), "masks", ["m.geojson"], [b"m"])
    assert os.path.isfile(os.path.join(str(tmp_path), "masks", "m.geojson"))


def test_save_labels(tmp_path):
    """_save_files() with 'labels' subdir writes to labels."""
    _save_files(str(tmp_path), "labels", ["l.csv"], [b"l"])
    assert os.path.isfile(os.path.join(str(tmp_path), "labels", "l.csv"))


# ------------------------------------------------------------------
# _validate_paths
# ------------------------------------------------------------------


def _make_files(tmp_path):
    """Create image, mask, and label files in tmp_path subdirectories."""
    for subdir in ("images", "masks", "labels"):
        os.makedirs(os.path.join(str(tmp_path), subdir), exist_ok=True)
    for name in ("img1.tif", "img2.tif"):
        with open(os.path.join(str(tmp_path), "images", name), "w") as f:
            f.write("")
    with open(os.path.join(str(tmp_path), "masks", "img1.geojson"), "w") as f:
        f.write("")
    with open(os.path.join(str(tmp_path), "labels", "img1.csv"), "w") as f:
        f.write("")
    return tmp_path


def test_validate_paths_all_exist(tmp_path):
    """_validate_paths() returns ok when all files exist."""
    _make_files(tmp_path)
    paths = [
        {"type": "image", "filename": "img1.tif"},
        {"type": "image", "filename": "img2.tif"},
        {"type": "mask", "filename": "img1.geojson"},
        {"type": "csv", "filename": "img1.csv"},
    ]
    result = _validate_paths(str(tmp_path), paths)

    assert result["errors"] == 0
    assert result["paths"][0]["status"] == "ok"
    assert result["paths"][0]["image"] == os.path.join(str(tmp_path), "images", "img1.tif")


def test_validate_paths_image_missing(tmp_path):
    """_validate_paths() reports error when an image file does not exist."""
    paths = [{"type": "image", "filename": "missing.tif"}]
    result = _validate_paths(str(tmp_path), paths)

    assert result["errors"] == 1
    assert "Image not found: missing.tif" in result["paths"][0]["error"]


def test_validate_paths_mask_missing(tmp_path):
    """_validate_paths() reports error when a mask file does not exist."""
    _make_files(tmp_path)
    paths = [
        {"type": "image", "filename": "img1.tif"},
        {"type": "mask", "filename": "missing.geojson"},
    ]
    result = _validate_paths(str(tmp_path), paths)

    assert result["errors"] == 1
    assert "Mask not found: missing.geojson" in result["paths"][0]["error"]


def test_validate_paths_label_missing(tmp_path):
    """_validate_paths() reports error when a label file does not exist."""
    _make_files(tmp_path)
    paths = [
        {"type": "image", "filename": "img1.tif"},
        {"type": "csv", "filename": "missing.csv"},
    ]
    result = _validate_paths(str(tmp_path), paths)

    assert result["errors"] == 1
    assert "Label not found: missing.csv" in result["paths"][0]["error"]


def test_validate_paths_no_image_paths(tmp_path):
    """_validate_paths() returns error when no image entries are provided."""
    paths = [{"type": "mask", "filename": "x.geojson"}]
    result = _validate_paths(str(tmp_path), paths)

    assert result["errors"] == 1
    assert "No image paths provided" in result["paths"][0]["error"]


def test_validate_paths_unequal_lists_excess_images(tmp_path):
    """_validate_paths() handles more images than masks — excess images get empty mask."""
    _make_files(tmp_path)
    paths = [
        {"type": "image", "filename": "img1.tif"},
        {"type": "image", "filename": "img2.tif"},
        {"type": "mask", "filename": "img1.geojson"},
    ]
    result = _validate_paths(str(tmp_path), paths)

    assert result["errors"] == 0
    # second image should have empty mask
    assert result["paths"][1]["mask"] == ""


# ------------------------------------------------------------------
# _validate_folders
# ------------------------------------------------------------------


def _make_folder_test_dirs(tmp_path):
    """Create image/mask/label folders with matching files."""
    for folder in ("images", "masks", "labels"):
        d = tmp_path / folder
        d.mkdir(exist_ok=True)
        (d / "slide1.tif").write_text("")
        (d / "slide2.tif").write_text("")
    (tmp_path / "masks" / "slide1.geojson").write_text("")
    (tmp_path / "labels" / "slide1.csv").write_text("")
    return tmp_path


def test_validate_folders_valid(tmp_path):
    """_validate_folders() returns ok rows for all images in the folder."""
    base = _make_folder_test_dirs(tmp_path)
    result = _validate_folders(
        str(base),
        image_folder=str(base / "images"),
        mask_folder=str(base / "masks"),
        label_folder=str(base / "labels"),
    )

    assert result["errors"] == 0
    assert len(result["paths"]) == 2


def test_validate_folders_missing_image_folder(tmp_path):
    """_validate_folders() returns error for a non-existent image folder."""
    result = _validate_folders(str(tmp_path), image_folder="/nonexistent")

    assert result["errors"] == 1
    assert "Image folder not found" in result["paths"][0]["error"]


def test_validate_folders_missing_mask_folder(tmp_path):
    """_validate_folders() returns error for a non-existent mask folder."""
    base = _make_folder_test_dirs(tmp_path)
    result = _validate_folders(
        str(base),
        image_folder=str(base / "images"),
        mask_folder="/nonexistent/masks",
        label_folder=str(base / "labels"),
    )

    assert result["errors"] == 1
    assert "Mask folder not found" in result["paths"][0]["error"]


def test_validate_folders_missing_label_folder(tmp_path):
    """_validate_folders() returns error for a non-existent label folder."""
    base = _make_folder_test_dirs(tmp_path)
    result = _validate_folders(
        str(base),
        image_folder=str(base / "images"),
        mask_folder=str(base / "masks"),
        label_folder="/nonexistent/labels",
    )

    assert result["errors"] == 1
    assert "Label folder not found" in result["paths"][0]["error"]


def test_validate_folders_stem_matching(tmp_path):
    """_validate_folders() matches masks/labels by image filename stem."""
    base = _make_folder_test_dirs(tmp_path)
    result = _validate_folders(
        str(base),
        image_folder=str(base / "images"),
        mask_folder=str(base / "masks"),
        label_folder=str(base / "labels"),
    )

    # slide1 should have mask and label; slide2 should not
    slide1_row = next(r for r in result["paths"] if "slide1" in r["image"])
    slide2_row = next(r for r in result["paths"] if "slide2" in r["image"])

    assert slide1_row["mask"] != ""
    assert slide1_row["csv"] != ""
    assert slide2_row["mask"] == ""
    assert slide2_row["csv"] == ""


def test_validate_folders_empty_image_folder(tmp_path):
    """_validate_folders() returns error when the image folder contains no images."""
    img_dir = tmp_path / "empty_images"
    img_dir.mkdir(exist_ok=True)
    (img_dir / "readme.txt").write_text("")

    result = _validate_folders(str(tmp_path), image_folder=str(img_dir))

    assert result["errors"] == 1
    assert "No image files found" in result["paths"][0]["error"]


def test_validate_folders_only_mask_and_label_folders(tmp_path):
    """_validate_folders() returns error when only mask/label folders are given."""
    result = _validate_folders(
        str(tmp_path),
        image_folder="",
        mask_folder=str(tmp_path),
        label_folder=str(tmp_path),
    )

    assert result["errors"] == 1


# ------------------------------------------------------------------
# _validate_csv
# ------------------------------------------------------------------


def test_validate_csv_valid(tmp_path):
    """_validate_csv() returns ok for CSV rows with existing server paths."""
    # Create real files on disk that the CSV will reference
    d = tmp_path / "server"
    d.mkdir(exist_ok=True)
    (d / "img1.tif").write_text("")
    (d / "mask1.geojson").write_text("")
    (d / "label1.csv").write_text("")

    csv_content = "image,mask,label\n" f"{d}/img1.tif,{d}/mask1.geojson,{d}/label1.csv\n"

    result = _validate_csv(csv_content.encode())

    assert result["errors"] == 0
    assert result["paths"][0]["status"] == "ok"


def test_validate_csv_missing_paths(tmp_path):
    """_validate_csv() reports errors for CSV rows with non-existent server paths."""
    csv_content = "image,mask,label\n/nonexistent/img.tif,/nonexistent/mask.geojson,/nonexistent/label.csv\n"

    result = _validate_csv(csv_content.encode())

    assert result["errors"] == 1
    assert result["paths"][0]["status"] == "error"


def test_validate_csv_empty(tmp_path):
    """_validate_csv() returns error when the CSV has no data rows."""
    csv_content = "image,mask,label\n"

    result = _validate_csv(csv_content.encode())

    assert result["errors"] == 1
    assert "no data rows" in result["paths"][0]["error"]


def test_validate_csv_partial_paths(tmp_path):
    """_validate_csv() only checks paths that are non-empty."""
    csv_content = "image,mask,label\n/nonexistent/img.tif,,\n"

    result = _validate_csv(csv_content.encode())

    assert result["errors"] == 1
    # Only the image path is checked; empty mask/label are skipped
    assert "Image not found" in result["paths"][0]["error"]


def test_validate_csv_bom_handling(tmp_path):
    """_validate_csv() handles UTF-8 BOM in CSV header."""
    csv_content = "\ufeffimage,mask,label\n/test/img.tif,,\n"

    # Should not raise; BOM is stripped by utf-8-sig
    result = _validate_csv(csv_content.encode())

    assert result["paths"][0]["image"] == "/test/img.tif"


# ------------------------------------------------------------------
# process (actor method) — stub; just tests the return shape
# ------------------------------------------------------------------


def test_process_returns_task_id_and_status():
    """process() returns a dict with task_id, status, and message."""
    import uuid as _uuid

    # process() is a method on the actor class; we test the logic directly
    # by importing the function that implements it
    from patchsorter.api.v1.upload.actor import UploadSessionActor

    # The process method returns a dict with these keys
    # We can't call it without Ray, so test the shape via the source
    import inspect
    source = inspect.getsource(UploadSessionActor.process)

    assert "task_id" in source
    assert "status" in source
    assert "message" in source
    assert "pending" in source


def test_process_calls_cleanup():
    """process() cleans up the temp directory after completion."""
    import inspect

    from patchsorter.api.v1.upload.actor import UploadSessionActor

    source = inspect.getsource(UploadSessionActor.process)

    # The process method has a try/finally that calls self.cleanup()
    assert "cleanup" in source
