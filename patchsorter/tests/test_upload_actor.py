"""Tests for _validate_mixed — the unified validation function.

Covers folder mode, file-drop mode (session temp dir only), mixed mode
(file-drop images + server mask/CSV), and edge cases.
"""

import os
import tempfile

import pytest

from patchsorter.api.v1.upload.actor import _validate_mixed


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


_test_session_id = "test-session-id"


def _create_session_dirs(tmp_path):
    """Create session temp dir structure with images subdirectory."""
    tmpdir = tmp_path / "session"
    (tmpdir / "images").mkdir(parents=True)
    (tmpdir / "masks").mkdir(parents=True)
    (tmpdir / "patch_csvs").mkdir(parents=True)
    return tmpdir, _test_session_id


def _write_image(tmpdir, name):
    (tmpdir / "images" / name).write_text("")


def _write_mask(tmpdir, stem):
    (tmpdir / "masks" / f"{stem}.geojson").write_text("")


def _write_csv(tmpdir, stem):
    (tmpdir / "patch_csvs" / f"{stem}.csv").write_text("")


def _write_server_file(folder, name):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text("")


# ------------------------------------------------------------------
# Folder mode — only server folders, no uploaded files
# ------------------------------------------------------------------


def test_folder_mode_all_labels(tmp_path):
    """All images have matching mask and CSV."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    server_mask = tmp_path / "server_masks"
    server_csv = tmp_path / "server_csvs"

    for name in ("slide1.tif", "slide2.tif"):
        _write_server_file(server_img, name)

    _write_server_file(server_mask, "slide1.geojson")
    _write_server_file(server_mask, "slide2.geojson")
    _write_server_file(server_csv, "slide1.csv")
    _write_server_file(server_csv, "slide2.csv")

    result = _validate_mixed(
        str(session),
        image_folder=str(server_img),
        mask_folder=str(server_mask),
        patch_csv_folder=str(server_csv),
    )

    assert result["errors"] == 0
    assert len(result["paths"]) == 2
    slide1 = next(r for r in result["paths"] if "slide1" in r["image"])
    slide2 = next(r for r in result["paths"] if "slide2" in r["image"])
    assert slide1["mask"] != ""
    assert slide1["csv"] != ""
    assert slide2["mask"] != ""
    assert slide2["csv"] != ""


def test_folder_mode_only_mask(tmp_path):
    """Only mask folder provided — CSV rows should be empty."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    server_mask = tmp_path / "server_masks"

    _write_server_file(server_img, "img1.tif")
    _write_server_file(server_mask, "img1.geojson")

    result = _validate_mixed(
        str(session),
        image_folder=str(server_img),
        mask_folder=str(server_mask),
    )

    assert result["errors"] == 0
    assert result["paths"][0]["status"] == "ok"
    assert result["paths"][0]["mask"] != ""
    assert result["paths"][0]["csv"] == ""


def test_folder_mode_only_csv(tmp_path):
    """Only patch_csv folder provided — mask rows should be empty."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    server_csv = tmp_path / "server_csvs"

    _write_server_file(server_img, "img1.tif")
    _write_server_file(server_csv, "img1.csv")

    result = _validate_mixed(
        str(session),
        image_folder=str(server_img),
        patch_csv_folder=str(server_csv),
    )

    assert result["errors"] == 0
    assert result["paths"][0]["status"] == "ok"
    assert result["paths"][0]["mask"] == ""
    assert result["paths"][0]["csv"] != ""


def test_folder_mode_neither_label(tmp_path):
    """No mask or CSV folders — all rows should error."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"

    _write_server_file(server_img, "img1.tif")

    result = _validate_mixed(
        str(session),
        image_folder=str(server_img),
    )

    assert result["errors"] == 1
    assert "No mask or patch CSV found" in result["paths"][0]["error"]


def test_folder_mode_empty_image_folder(tmp_path):
    """Empty image folder raises Exception."""
    session, session_id = _create_session_dirs(tmp_path)
    empty_img = tmp_path / "empty_imgs"
    empty_img.mkdir()

    with pytest.raises(Exception, match="No valid images found in image folder"):
        _validate_mixed(
            str(session),
            image_folder=str(empty_img),
        )


def test_folder_mode_missing_image_folder(tmp_path):
    """Non-existent image folder raises Exception."""
    session, session_id = _create_session_dirs(tmp_path)

    with pytest.raises(Exception, match="Image folder does not exist"):
        _validate_mixed(
            str(session),
            image_folder="/nonexistent/path",
        )


def test_folder_mode_multiple_images_partial_labels(tmp_path):
    """Multiple images with partial mask/CSV coverage."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    server_mask = tmp_path / "server_masks"
    server_csv = tmp_path / "server_csvs"

    for name in ("a.tif", "b.tif", "c.tif"):
        _write_server_file(server_img, name)

    _write_server_file(server_mask, "a.geojson")
    _write_server_file(server_csv, "b.csv")

    result = _validate_mixed(
        str(session),
        image_folder=str(server_img),
        mask_folder=str(server_mask),
        patch_csv_folder=str(server_csv),
    )

    assert result["errors"] == 1  # only c.tif has no labels
    assert len(result["paths"]) == 3
    a_row = next(r for r in result["paths"] if "a.tif" in r["image"])
    b_row = next(r for r in result["paths"] if "b.tif" in r["image"])
    c_row = next(r for r in result["paths"] if "c.tif" in r["image"])
    assert a_row["mask"] != "" and a_row["csv"] == ""
    assert b_row["mask"] == "" and b_row["csv"] != ""
    assert c_row["mask"] == "" and c_row["csv"] == ""


def test_folder_mode_stem_matching_case_insensitive(tmp_path):
    """Mask/CSV matching is case-insensitive on extension."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    server_mask = tmp_path / "server_masks"

    _write_server_file(server_img, "img1.TIF")  # uppercase extension
    _write_server_file(server_mask, "img1.GEOJSON")  # uppercase extension

    result = _validate_mixed(
        str(session),
        image_folder=str(server_img),
        mask_folder=str(server_mask),
    )

    assert result["errors"] == 0
    assert result["paths"][0]["status"] == "ok"
    assert result["paths"][0]["mask"] != ""


# ------------------------------------------------------------------
# File-drop mode — only session temp dir, no server folders
# ------------------------------------------------------------------


def test_file_drop_all_labels(tmp_path):
    """All labels uploaded to session temp dir."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_image(session, "img2.tif")
    _write_mask(session, "img1")
    _write_mask(session, "img2")
    _write_csv(session, "img1")
    _write_csv(session, "img2")

    result = _validate_mixed(str(session))

    assert result["errors"] == 0
    assert len(result["paths"]) == 2
    img1 = next(r for r in result["paths"] if "img1" in r["image"])
    img2 = next(r for r in result["paths"] if "img2" in r["image"])
    assert img1["mask"] != ""
    assert img1["csv"] != ""
    assert img2["mask"] != ""
    assert img2["csv"] != ""


def test_file_drop_only_mask(tmp_path):
    """Only mask uploaded — CSV rows should be empty."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_mask(session, "img1")

    result = _validate_mixed(str(session))

    assert result["errors"] == 0
    assert result["paths"][0]["status"] == "ok"
    assert result["paths"][0]["mask"] != ""
    assert result["paths"][0]["csv"] == ""


def test_file_drop_only_csv(tmp_path):
    """Only patch CSV uploaded — mask rows should be empty."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_csv(session, "img1")

    result = _validate_mixed(str(session))

    assert result["errors"] == 0
    assert result["paths"][0]["status"] == "ok"
    assert result["paths"][0]["mask"] == ""
    assert result["paths"][0]["csv"] != ""


def test_file_drop_neither_label(tmp_path):
    """No labels uploaded — all rows should error."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")

    result = _validate_mixed(str(session))

    assert result["errors"] == 1
    assert "No mask or patch CSV found" in result["paths"][0]["error"]


def test_file_drop_no_images(tmp_path):
    """No images in session temp dir — returns error."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_mask(session, "img1")
    _write_csv(session, "img1")

    result = _validate_mixed(str(session))

    assert result["errors"] == 1
    assert "No images found" in result["paths"][0]["error"]


def test_file_drop_unequal_lists(tmp_path):
    """Uploaded more masks than images — extra masks are ignored."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_image(session, "img2.tif")
    _write_mask(session, "img1")
    _write_mask(session, "img3")  # no matching image

    result = _validate_mixed(str(session))

    assert result["errors"] == 1  # img2 has no labels
    assert len(result["paths"]) == 2  # only 2 images


# ------------------------------------------------------------------
# Mixed mode — file-drop images + server mask/CSV
# ------------------------------------------------------------------


def test_mixed_file_drop_images_server_mask(tmp_path):
    """Images uploaded, mask on server — both should be matched."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_image(session, "img2.tif")

    server_mask = tmp_path / "server_masks"
    _write_server_file(server_mask, "img1.geojson")

    result = _validate_mixed(
        str(session),
        mask_folder=str(server_mask),
    )

    assert result["errors"] == 1  # img2 has no labels
    img1 = next(r for r in result["paths"] if "img1" in r["image"])
    img2 = next(r for r in result["paths"] if "img2" in r["image"])
    assert img1["mask"] != ""
    assert img2["mask"] == ""


def test_mixed_file_drop_images_server_csv(tmp_path):
    """Images uploaded, CSV on server — both should be matched."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_image(session, "img2.tif")

    server_csv = tmp_path / "server_csvs"
    _write_server_file(server_csv, "img2.csv")

    result = _validate_mixed(
        str(session),
        patch_csv_folder=str(server_csv),
    )

    assert result["errors"] == 1  # img1 has no labels
    img1 = next(r for r in result["paths"] if "img1" in r["image"])
    img2 = next(r for r in result["paths"] if "img2" in r["image"])
    assert img1["csv"] == ""
    assert img2["csv"] != ""


def test_mixed_file_drop_images_both_server_labels(tmp_path):
    """Images uploaded, mask+CSV on server — all matched."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_image(session, "img2.tif")

    server_mask = tmp_path / "server_masks"
    server_csv = tmp_path / "server_csvs"
    _write_server_file(server_mask, "img1.geojson")
    _write_server_file(server_csv, "img2.csv")

    result = _validate_mixed(
        str(session),
        mask_folder=str(server_mask),
        patch_csv_folder=str(server_csv),
    )

    assert result["errors"] == 0
    img1 = next(r for r in result["paths"] if "img1" in r["image"])
    img2 = next(r for r in result["paths"] if "img2" in r["image"])
    assert img1["mask"] != "" and img1["csv"] == ""
    assert img2["mask"] == "" and img2["csv"] != ""


def test_mixed_server_images_file_drop_masks(tmp_path):
    """Images on server, masks uploaded — both should be matched."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    _write_server_file(server_img, "img1.tif")
    _write_server_file(server_img, "img2.tif")

    _write_mask(session, "img1")
    _write_mask(session, "img2")

    result = _validate_mixed(
        str(session),
        image_folder=str(server_img),
    )

    assert result["errors"] == 0
    img1 = next(r for r in result["paths"] if "img1" in r["image"])
    img2 = next(r for r in result["paths"] if "img2" in r["image"])
    assert img1["mask"] != ""
    assert img2["mask"] != ""


def test_mixed_partial_server_match(tmp_path):
    """Some images have server labels, others have uploaded labels."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_image(session, "img2.tif")

    server_mask = tmp_path / "server_masks"
    server_csv = tmp_path / "server_csvs"
    _write_server_file(server_mask, "img1.geojson")
    _write_server_file(server_csv, "img2.csv")

    result = _validate_mixed(
        str(session),
        mask_folder=str(server_mask),
        patch_csv_folder=str(server_csv),
    )

    assert result["errors"] == 0
    img1 = next(r for r in result["paths"] if "img1" in r["image"])
    img2 = next(r for r in result["paths"] if "img2" in r["image"])
    assert img1["mask"] != "" and img1["csv"] == ""
    assert img2["mask"] == "" and img2["csv"] != ""


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


def test_empty_all_inputs(tmp_path):
    """No images, no folders — returns error."""
    session, session_id = _create_session_dirs(tmp_path)

    result = _validate_mixed(str(session))

    assert result["errors"] == 1
    assert "No images found" in result["paths"][0]["error"]


def test_whitespace_filenames(tmp_path):
    """Whitespace in filenames is preserved (not stripped)."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "  img1  .tif")
    _write_mask(session, "  img1  ")

    result = _validate_mixed(str(session))

    assert result["errors"] == 0
    assert result["paths"][0]["status"] == "ok"
    assert result["paths"][0]["mask"] != ""


def test_duplicate_stems_server_overwrites(tmp_path):
    """When same stem exists in both server and temp dir, server path wins."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_mask(session, "img1")

    server_img = tmp_path / "server_imgs"
    _write_server_file(server_img, "img1.tif")
    _write_server_file(server_img / "..", "img1.geojson")  # dummy to make path work

    server_mask = tmp_path / "server_masks"
    _write_server_file(server_mask, "img1.geojson")

    result = _validate_mixed(
        str(session),
        image_folder=str(server_img),
        mask_folder=str(server_mask),
    )

    assert result["errors"] == 0
    img1 = result["paths"][0]
    assert "server_imgs" in img1["image"]
    assert "server_masks" in img1["mask"]


def test_no_mask_no_csv_folder(tmp_path):
    """Both mask and CSV folders missing but both have uploaded labels."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_mask(session, "img1")
    _write_csv(session, "img1")

    result = _validate_mixed(str(session))

    assert result["errors"] == 0
    assert result["paths"][0]["mask"] != ""
    assert result["paths"][0]["csv"] != ""


def test_only_mask_folder_no_csv_folder(tmp_path):
    """Only mask folder provided, no CSV folder — mask found, csv empty."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    server_mask = tmp_path / "server_masks"

    _write_server_file(server_img, "img1.tif")
    _write_server_file(server_mask, "img1.geojson")

    result = _validate_mixed(
        str(session),
        image_folder=str(server_img),
        mask_folder=str(server_mask),
    )

    assert result["errors"] == 0
    assert result["paths"][0]["mask"] != ""
    assert result["paths"][0]["csv"] == ""


def test_only_csv_folder_no_mask_folder(tmp_path):
    """Only CSV folder provided, no mask folder — CSV found, mask empty."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    server_csv = tmp_path / "server_csvs"

    _write_server_file(server_img, "img1.tif")
    _write_server_file(server_csv, "img1.csv")

    result = _validate_mixed(
        str(session),
        image_folder=str(server_img),
        patch_csv_folder=str(server_csv),
    )

    assert result["errors"] == 0
    assert result["paths"][0]["mask"] == ""
    assert result["paths"][0]["csv"] != ""


def test_both_folders_empty(tmp_path):
    """Both folders exist but are empty — raises Exception for empty image folder."""
    session, session_id = _create_session_dirs(tmp_path)
    empty_img = tmp_path / "empty_img"
    empty_mask = tmp_path / "empty_mask"
    empty_csv = tmp_path / "empty_csv"
    empty_img.mkdir()
    empty_mask.mkdir()
    empty_csv.mkdir()

    with pytest.raises(Exception, match="No valid images found in image folder"):
        _validate_mixed(
            str(session),
            image_folder=str(empty_img),
            mask_folder=str(empty_mask),
            patch_csv_folder=str(empty_csv),
        )


def test_mixed_both_sources_same_stem(tmp_path):
    """Same stem in both temp dir and server — server path should win for that type."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_mask(session, "img1")

    server_img = tmp_path / "server_imgs"
    server_mask = tmp_path / "server_masks"
    _write_server_file(server_img, "img1.tif")
    _write_server_file(server_mask, "img1.geojson")

    result = _validate_mixed(
        str(session),
        image_folder=str(server_img),
        mask_folder=str(server_mask),
    )

    assert result["errors"] == 0
    img1 = result["paths"][0]
    assert "server_imgs" in img1["image"]
    assert "server_masks" in img1["mask"]


def test_nonexistent_mask_folder_raises(tmp_path):
    """Non-existent mask folder raises Exception."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_mask(session, "img1")

    with pytest.raises(Exception, match="Mask folder does not exist"):
        _validate_mixed(
            str(session),
            mask_folder="/nonexistent/mask/folder",
        )


def test_nonexistent_csv_folder_raises(tmp_path):
    """Non-existent CSV folder raises Exception."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")
    _write_csv(session, "img1")

    with pytest.raises(Exception, match="Patch CSV folder does not exist"):
        _validate_mixed(
            str(session),
            patch_csv_folder="/nonexistent/csv/folder",
        )


def test_many_images_sorted(tmp_path):
    """Many images should be sorted alphabetically by stem."""
    session, session_id = _create_session_dirs(tmp_path)
    for name in ["z.tif", "a.tif", "m.tif"]:
        _write_image(session, name)

    result = _validate_mixed(str(session))

    assert result["errors"] == 3  # no labels for any image
    assert len(result["paths"]) == 3
    stems = [r["image"].split("/")[-1].replace(".tif", "") for r in result["paths"]]
    assert stems == sorted(stems)


# ------------------------------------------------------------------
# Missing/empty folder exception tests
# ------------------------------------------------------------------


def test_missing_image_folder_raises(tmp_path):
    """Non-existent image_folder should raise Exception."""
    session, session_id = _create_session_dirs(tmp_path)
    _write_image(session, "img1.tif")

    with pytest.raises(Exception, match="Image folder does not exist"):
        _validate_mixed(
            str(session),
            image_folder="/nonexistent/image/folder",
        )


def test_empty_image_folder_raises(tmp_path):
    """Image_folder with no valid images should raise Exception."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    server_img.mkdir(parents=True)
    (server_img / "readme.txt").write_text("not an image")

    with pytest.raises(Exception, match="No valid images found in image folder"):
        _validate_mixed(
            str(session),
            image_folder=str(server_img),
        )


def test_missing_mask_folder_raises(tmp_path):
    """Non-existent mask_folder should raise Exception."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    _write_server_file(server_img, "img1.tif")

    with pytest.raises(Exception, match="Mask folder does not exist"):
        _validate_mixed(
            str(session),
            image_folder=str(server_img),
            mask_folder="/nonexistent/mask/folder",
        )


def test_empty_mask_folder_raises(tmp_path):
    """Mask_folder with no .geojson files should raise Exception."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    server_mask = tmp_path / "server_masks"
    _write_server_file(server_img, "img1.tif")
    server_mask.mkdir(parents=True)
    (server_mask / "readme.txt").write_text("not a mask")

    with pytest.raises(Exception, match="No valid mask files found in mask folder"):
        _validate_mixed(
            str(session),
            image_folder=str(server_img),
            mask_folder=str(server_mask),
        )


def test_missing_csv_folder_raises(tmp_path):
    """Non-existent patch_csv_folder should raise Exception."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    _write_server_file(server_img, "img1.tif")

    with pytest.raises(Exception, match="Patch CSV folder does not exist"):
        _validate_mixed(
            str(session),
            image_folder=str(server_img),
            patch_csv_folder="/nonexistent/csv/folder",
        )


def test_empty_csv_folder_raises(tmp_path):
    """Patch_csv_folder with no .csv files should raise Exception."""
    session, session_id = _create_session_dirs(tmp_path)
    server_img = tmp_path / "server_imgs"
    server_csv = tmp_path / "server_csvs"
    _write_server_file(server_img, "img1.tif")
    server_csv.mkdir(parents=True)
    (server_csv / "readme.txt").write_text("not a csv")

    with pytest.raises(Exception, match="No valid patch CSV files found in patch CSV folder"):
        _validate_mixed(
            str(session),
            image_folder=str(server_img),
            patch_csv_folder=str(server_csv),
        )
