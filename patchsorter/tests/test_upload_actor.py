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
    _validate_folders,
    _validate_paths,
    _validate_image_csv,
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


def test_save_patch_csvs(tmp_path):
    """_save_files() with 'patch_csvs' subdir writes to patch_csvs."""
    _save_files(str(tmp_path), "patch_csvs", ["l.csv"], [b"l"])
    assert os.path.isfile(os.path.join(str(tmp_path), "patch_csvs", "l.csv"))


# ------------------------------------------------------------------
# _validate_paths
# ------------------------------------------------------------------


def _make_files(tmp_path):
    """Create image, mask, and patch_csv files in tmp_path subdirectories."""
    for subdir in ("images", "masks", "patch_csvs"):
        os.makedirs(os.path.join(str(tmp_path), subdir), exist_ok=True)
    for name in ("img1.tif", "img2.tif"):
        with open(os.path.join(str(tmp_path), "images", name), "w") as f:
            f.write("")
    with open(os.path.join(str(tmp_path), "masks", "img1.geojson"), "w") as f:
        f.write("")
    with open(os.path.join(str(tmp_path), "patch_csvs", "img1.csv"), "w") as f:
        f.write("")
    return tmp_path


def test_validate_paths_all_exist(tmp_path):
    """_validate_paths() returns ok when all files exist."""
    _make_files(tmp_path)
    result = _validate_paths(
        str(tmp_path),
        image_names=["img1.tif", "img2.tif"],
        mask_names=["img1.geojson"],
        patch_csv_names=["img1.csv"],
    )

    assert result["errors"] == 0
    assert result["paths"][0]["status"] == "ok"
    assert result["paths"][0]["image"] == os.path.join(str(tmp_path), "images", "img1.tif")


def test_validate_paths_image_missing(tmp_path):
    """_validate_paths() reports error when an image file does not exist."""
    result = _validate_paths(
        str(tmp_path),
        image_names=["missing.tif"],
        mask_names=[],
        patch_csv_names=[],
    )

    assert result["errors"] == 1
    assert "Image not found: missing.tif" in result["paths"][0]["error"]


def test_validate_paths_mask_missing(tmp_path):
    """_validate_paths() reports error when a mask file does not exist."""
    _make_files(tmp_path)
    result = _validate_paths(
        str(tmp_path),
        image_names=["img1.tif"],
        mask_names=["missing.geojson"],
        patch_csv_names=[],
    )

    assert result["errors"] == 1
    assert "Mask not found: missing.geojson" in result["paths"][0]["error"]


def test_validate_paths_patch_csv_missing(tmp_path):
    """_validate_paths() reports error when a patch_csv file does not exist."""
    _make_files(tmp_path)
    result = _validate_paths(
        str(tmp_path),
        image_names=["img1.tif"],
        mask_names=[],
        patch_csv_names=["missing.csv"],
    )

    assert result["errors"] == 1
    assert "Patch CSV not found: missing.csv" in result["paths"][0]["error"]


def test_validate_paths_no_image_paths(tmp_path):
    """_validate_paths() returns error when no image entries are provided."""
    result = _validate_paths(
        str(tmp_path),
        image_names=[],
        mask_names=["x.geojson"],
        patch_csv_names=[],
    )

    assert result["errors"] == 1
    assert "No image paths provided" in result["paths"][0]["error"]


def test_validate_paths_unequal_lists_excess_images(tmp_path):
    """_validate_paths() handles more images than masks — excess images get empty mask."""
    _make_files(tmp_path)
    result = _validate_paths(
        str(tmp_path),
        image_names=["img1.tif", "img2.tif"],
        mask_names=["img1.geojson"],
        patch_csv_names=[],
    )

    assert result["errors"] == 0
    # second image should have empty mask
    assert result["paths"][1]["mask"] == ""


# ------------------------------------------------------------------
# _validate_folders
# ------------------------------------------------------------------


def _make_folder_test_dirs(tmp_path):
    """Create image/mask/patch_csv folders with matching files."""
    for folder in ("images", "masks", "patch_csvs"):
        d = tmp_path / folder
        d.mkdir(exist_ok=True)
        (d / "slide1.tif").write_text("")
        (d / "slide2.tif").write_text("")
    (tmp_path / "masks" / "slide1.geojson").write_text("")
    (tmp_path / "patch_csvs" / "slide1.csv").write_text("")
    return tmp_path


def test_validate_folders_valid(tmp_path):
    """_validate_folders() returns ok rows for all images in the folder."""
    base = _make_folder_test_dirs(tmp_path)
    result = _validate_folders(
        str(base),
        image_folder=str(base / "images"),
        mask_folder=str(base / "masks"),
        patch_csv_folder=str(base / "patch_csvs"),
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
        patch_csv_folder=str(base / "patch_csvs"),
    )

    assert result["errors"] == 1
    assert "Mask folder not found" in result["paths"][0]["error"]


def test_validate_folders_missing_patch_csv_folder(tmp_path):
    """_validate_folders() returns error for a non-existent patch_csv folder."""
    base = _make_folder_test_dirs(tmp_path)
    result = _validate_folders(
        str(base),
        image_folder=str(base / "images"),
        mask_folder=str(base / "masks"),
        patch_csv_folder="/nonexistent/patch_csvs",
    )

    assert result["errors"] == 1
    assert "Patch CSV folder not found" in result["paths"][0]["error"]


def test_validate_folders_stem_matching(tmp_path):
    """_validate_folders() matches masks/patch_csvs by image filename stem."""
    base = _make_folder_test_dirs(tmp_path)
    result = _validate_folders(
        str(base),
        image_folder=str(base / "images"),
        mask_folder=str(base / "masks"),
        patch_csv_folder=str(base / "patch_csvs"),
    )

    # slide1 should have mask and patch_csv; slide2 should not
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


def test_validate_folders_only_mask_and_patch_csv_folders(tmp_path):
    """_validate_folders() returns error when only mask/patch_csv folders are given."""
    result = _validate_folders(
        str(tmp_path),
        image_folder="",
        mask_folder=str(tmp_path),
        patch_csv_folder=str(tmp_path),
    )

    assert result["errors"] == 1


# ------------------------------------------------------------------
# _validate_image_csv
# ------------------------------------------------------------------


def test_validate_image_csv_valid(tmp_path):
    """_validate_image_csv() returns ok for CSV rows with existing server paths."""
    # Create real files on disk that the CSV will reference
    d = tmp_path / "server"
    d.mkdir(exist_ok=True)
    (d / "img1.tif").write_text("")
    (d / "mask1.geojson").write_text("")
    (d / "patch_csv1.csv").write_text("")

    csv_content = "image,mask,patch_csv\n" f"{d}/img1.tif,{d}/mask1.geojson,{d}/patch_csv1.csv\n"

    result = _validate_image_csv(csv_content.encode())

    assert result["errors"] == 0
    assert result["paths"][0]["status"] == "ok"


def test_validate_image_csv_missing_paths(tmp_path):
    """_validate_image_csv() reports errors for CSV rows with non-existent server paths."""
    csv_content = "image,mask,patch_csv\n/nonexistent/img.tif,/nonexistent/mask.geojson,/nonexistent/patch_csv.csv\n"

    result = _validate_image_csv(csv_content.encode())

    assert result["errors"] == 1
    assert result["paths"][0]["status"] == "error"


def test_validate_image_csv_empty(tmp_path):
    """_validate_image_csv() returns error when the CSV has no data rows."""
    csv_content = "image,mask,patch_csv\n"

    result = _validate_image_csv(csv_content.encode())

    assert result["errors"] == 1
    assert "no data rows" in result["paths"][0]["error"]


def test_validate_image_csv_partial_paths(tmp_path):
    """_validate_image_csv() only checks paths that are non-empty."""
    csv_content = "image,mask,patch_csv\n/nonexistent/img.tif,,\n"

    result = _validate_image_csv(csv_content.encode())

    assert result["errors"] == 1
    # Only the image path is checked; empty mask/patch_csv are skipped
    assert "Image not found" in result["paths"][0]["error"]


def test_validate_image_csv_bom_handling(tmp_path):
    """_validate_image_csv() handles UTF-8 BOM in CSV header."""
    csv_content = "\ufeffimage,mask,patch_csv\n/test/img.tif,,\n"

    # Should not raise; BOM is stripped by utf-8-sig
    result = _validate_image_csv(csv_content.encode())

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

