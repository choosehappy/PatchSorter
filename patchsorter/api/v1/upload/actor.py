from __future__ import annotations

import csv
import io
import os
import uuid
from pathlib import Path
from typing import List
from typing import List
import ray
import large_image

from patchsorter.api.v1.upload.fsmanager import FileStoreManager
from patchsorter.api.v1.upload.models import ProcessRow
from patchsorter.api.v1.upload.patch_iterator import (
    CsvPatchIterator,
    GeojsonPatchIterator,
    HybridPatchIterator,
    PatchIterator,
)
from patchsorter.config import constants
from patchsorter.db.head_client import get_client
from patchsorter.db.head_client.patch import PatchStore
from patchsorter.db.head_client.image import ImageStore
from patchsorter.db.head_client.settings import SettingsStore
from patchsorter.utils.patch_extraction import (
    BASE_MAG_PPM_MICRONS,
    MAG_TO_PPM_FACTOR,
    compute_downsample_factor,
    estimate_object_radius_from_polygons,
    extract_patch_from_geometry,
    get_polygon_radius_in_pixels,
    mm_per_pixel_at_base,
)

_IMAGE_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}
_PATCH_BATCH_SIZE = 1000


# ------------------------------------------------------------------
# Core logic extracted into plain functions for testability.
# The actor delegates to these; tests call them directly with a tmpdir.
# ------------------------------------------------------------------

def _save_files(tmpdir: str, subdir: str, filenames: List[str], contents: List[bytes]) -> str:
    """Save files to *subdir* inside *tmpdir*. Returns a count message."""
    dest = os.path.join(tmpdir, subdir)
    os.makedirs(dest, exist_ok=True)
    for name, data in zip(filenames, contents):
        with open(os.path.join(dest, os.path.basename(name)), "wb") as f:
            f.write(data)
    return f"Uploaded {len(filenames)} {subdir.rstrip('s')}(s)"


def _validate_mixed(
    tmpdir: str,
    image_folder: str = "",
    mask_folder: str = "",
    patch_csv_folder: str = "",
) -> dict:
    """Glob all available files from the session temp dir and optional server folders, then match masks/patch_csvs by image filename stem.

    A row is valid if at least one of mask or CSV is found for the image.
    """
    images_dir = Path(tmpdir) / "images"
    masks_dir = Path(tmpdir) / "masks"
    patch_csvs_dir = Path(tmpdir) / "patch_csvs"

    # Gather image stems from all sources
    image_stems: dict[str, Path] = {}  # stem -> image filepath

    # From session temp dir (file-drop mode)
    if images_dir.is_dir():
        for f in images_dir.iterdir():
            if f.suffix.lower() in _IMAGE_EXTS:
                image_stems[f.stem] = f

    # From server-side image folder (folder mode)
    if image_folder:
        img_dir = Path(image_folder)
        if not img_dir.is_dir():
            raise Exception(f"Image folder does not exist: {image_folder}")
        found = False
        for f in img_dir.iterdir():
            if f.suffix.lower() in _IMAGE_EXTS:
                image_stems[f.stem] = f
                found = True
        if not found:
            raise Exception(f"No valid images found in image folder: {image_folder}")

    if not image_stems:
        return {
            "paths": [
                dict(image="", mask="", csv="", status="error",
                     error="No images found in session temp dir or image_folder"),
            ],
            "errors": 1,
        }

    # Gather masks from all sources
    mask_by_stem: dict[str, Path] = {}
    if masks_dir.is_dir():
        for f in masks_dir.iterdir():
            if f.suffix.lower() == ".geojson":
                mask_by_stem[f.stem] = f
    if mask_folder:
        mf = Path(mask_folder)
        if not mf.is_dir():
            raise Exception(f"Mask folder does not exist: {mask_folder}")
        found = False
        for f in mf.iterdir():
            if f.suffix.lower() == ".geojson":
                mask_by_stem[f.stem] = f
                found = True
        if not found:
            raise Exception(f"No valid mask files found in mask folder: {mask_folder}")

    # Gather patch_csvs from all sources
    csv_by_stem: dict[str, Path] = {}
    if patch_csvs_dir.is_dir():
        for f in patch_csvs_dir.iterdir():
            if f.suffix.lower() == ".csv":
                csv_by_stem[f.stem] = f
    if patch_csv_folder:
        pf = Path(patch_csv_folder)
        if not pf.is_dir():
            raise Exception(f"Patch CSV folder does not exist: {patch_csv_folder}")
        found = False
        for f in pf.iterdir():
            if f.suffix.lower() == ".csv":
                csv_by_stem[f.stem] = f
                found = True
        if not found:
            raise Exception(f"No valid patch CSV files found in patch CSV folder: {patch_csv_folder}")

    rows: list[dict] = []
    for stem in sorted(image_stems.keys()):
        img_path = image_stems[stem]
        img_rel = os.path.relpath(str(img_path), constants.MOUNTS_PATH)
        mask_rel = os.path.relpath(str(mask_by_stem[stem]), constants.MOUNTS_PATH) if stem in mask_by_stem else ""
        csv_rel = os.path.relpath(str(csv_by_stem[stem]), constants.MOUNTS_PATH) if stem in csv_by_stem else ""

        base_mag: float | None = None
        if img_rel:
            try:
                ts = large_image.open(str(img_path))
                base_mag = ts.getMetadata().get("magnification")
            except Exception:
                base_mag = None

        if not mask_rel and not csv_rel:
            rows.append(
                dict(
                    image=img_rel,
                    mask=mask_rel,
                    csv=csv_rel,
                    status="error",
                    error=f"No mask or patch CSV found for {img_path.name}",
                    base_mag=base_mag,
                )
            )
        else:
            rows.append(
                dict(
                    image=img_rel,
                    mask=mask_rel,
                    csv=csv_rel,
                    status="ok",
                    error="",
                    base_mag=base_mag,
                )
            )

    return {"paths": rows, "errors": sum(1 for r in rows if r["status"] == "error")}


def _validate_image_csv(csv_content: bytes) -> dict:
    """Parse an image manifest CSV and validate that each path exists on the server."""
    text = csv_content.decode("utf-8-sig")  # handle BOM
    reader = csv.DictReader(io.StringIO(text))

    rows: list[dict] = []
    for row in reader:
        img = (row.get("image") or "").strip()
        mask = (row.get("mask") or "").strip()
        patch_csv = (row.get("patch_csv") or "").strip()

        errors: list[str] = []
        if img and not os.path.exists(os.path.join(constants.MOUNTS_PATH, img)):
            errors.append(f"Image not found: {img}")
        if mask and not os.path.exists(os.path.join(constants.MOUNTS_PATH, mask)):
            errors.append(f"Mask not found: {mask}")
        if patch_csv and not os.path.exists(os.path.join(constants.MOUNTS_PATH, patch_csv)):
            errors.append(f"Patch CSV not found: {patch_csv}")

        base_mag: float | None = None
        if img:
            resolved = os.path.join(constants.MOUNTS_PATH, img)
            if os.path.exists(resolved):
                try:
                    ts = large_image.open(resolved)
                    base_mag = ts.getMetadata().get("magnification")
                except Exception:
                    base_mag = None

        rows.append(
            dict(
                image=img,
                mask=mask,
                csv=patch_csv,
                status="error" if errors else "ok",
                error="; ".join(errors),
                base_mag=base_mag,
            )
        )

    if not rows:
        rows.append(
            dict(image="", mask="", csv="", status="error", error="CSV file contains no data rows")
        )

    return {"paths": rows, "errors": sum(1 for r in rows if r["status"] == "error")}


# ------------------------------------------------------------------
# process_row Ray remote function
# ------------------------------------------------------------------


@ray.remote
def process_row(
    process_row_arg: ProcessRow,
    project_id: int,
    session_id: str,
    settings: dict,
) -> dict:
    """Ray remote function to process a single upload row.

    Extracts patches from an image using geometries from a mask or CSV,
    and bulk-inserts them into the database.

    Args:
        process_row_arg: ProcessRow with image/mask/csv paths.
        project_id: Target project ID.
        session_id: Upload session ID.
        settings: Pre-loaded project settings dict with keys:
            patch_size, patch_extraction_method, object_radius.

    Returns:
        Dict with image_id and patch_count.

    Raises:
        Exception: Any error during processing propagates to the caller.
    """
    fsman = FileStoreManager()

    # Resolve paths: ProcessRow fields are paths relative to MOUNTS_PATH
    image_path = os.path.join(constants.MOUNTS_PATH, process_row_arg.image)
    image_filename = os.path.basename(image_path)
    mask_path = os.path.join(constants.MOUNTS_PATH, process_row_arg.mask) if process_row_arg.mask else None
    csv_path = os.path.join(constants.MOUNTS_PATH, process_row_arg.csv) if process_row_arg.csv else None

    # Open image tile source
    ts = large_image.open(image_path)

    # Determine base_mag
    if process_row_arg.base_mag is not None:
        base_mag = process_row_arg.base_mag
    else:
        base_mag = ts.getMetadata().get("magnification")
    if base_mag is None:
        raise ValueError(
            f"base_mag not provided and could not be extracted from image metadata "
            f"for {image_path}"
        )

    # Collect image metadata
    base_width = ts.getMetadata().get("width", 0)
    base_height = ts.getMetadata().get("height", 0)
    deepzoom_tilesize = ts.getMetadata().get("tileWidth", 256)

    # Determine iterator based on which files are present
    has_mask = mask_path is not None and os.path.exists(mask_path)
    has_csv = csv_path is not None and os.path.exists(csv_path)

    if has_mask and not has_csv:
        iterator: PatchIterator = GeojsonPatchIterator(mask_path)
    elif has_csv and not has_mask:
        iterator = CsvPatchIterator(csv_path)
    elif has_mask and has_csv:
        iterator = HybridPatchIterator(mask_path, csv_path)
    else:
        raise ValueError("No mask or CSV file found for image")

    # Load settings (passed from UploadSessionActor — no extra DB round-trip needed)
    patch_size: int = int(settings.get("patch_size", 64))
    patch_extraction_method: str = settings.get("patch_extraction_method", "use estimated object size")
    object_radius_str: str | None = settings.get("object_radius")
    object_radius: float | None = float(object_radius_str) if object_radius_str else None

    # Determine downsample strategy
    mm_per_pixel = mm_per_pixel_at_base(base_mag)

    # Collect all geometries upfront (required to estimate object size from first 5 polygons)
    geometries: list = []
    for geometry, label, patch_uuid in iterator:
        geometries.append((geometry, label, patch_uuid))

    # Determine downsample approach from project setting
    if patch_extraction_method == "use estimated object size":
        if not geometries:
            raise ValueError("No geometries found in iterator")
        avg_radius = estimate_object_radius_from_polygons([g for g, _, _ in geometries])
        avg_radius_microns = avg_radius * mm_per_pixel * 1000
        downsample = compute_downsample_factor(avg_radius_microns, base_mag, patch_size, mm_per_pixel)
        per_patch_downsample = False

    elif patch_extraction_method == "use manual object radius":
        if object_radius is None:
            raise ValueError("object_radius setting is required when patch_extraction_method is 'use manual object radius'")
        downsample = compute_downsample_factor(object_radius, base_mag, patch_size, mm_per_pixel)
        per_patch_downsample = False

    elif patch_extraction_method == "fit all objects":
        per_patch_downsample = True
        downsample = 1.0  # unused but keeps type-checker happy
    else:
        raise ValueError(f"Unknown patch_extraction_method: {patch_extraction_method}")

    # Single DB session: insert image record then batch-insert patches via COPY
    with get_client().get_session() as session:
        result = ImageStore(session).create(
            project_id=project_id,
            name=image_filename,
            image_path=image_path,
            base_mag=base_mag,
            base_width=base_width,
            base_height=base_height,
            deepzoom_tilesize=deepzoom_tilesize,
        )
        image_id = result["image_id"]

        patch_store = PatchStore(project_id, session)
        batch: list[tuple] = []
        total_patches = 0

        for geometry, label, patch_uuid in geometries:
            if per_patch_downsample:
                radius_pixels = get_polygon_radius_in_pixels(geometry)
                radius_microns = radius_pixels * mm_per_pixel * 1000
                computed_downsample = compute_downsample_factor(radius_microns, base_mag, patch_size, mm_per_pixel)
            else:
                computed_downsample = downsample

            patch_bytes = extract_patch_from_geometry(ts, geometry, patch_size, computed_downsample, base_mag)

            if geometry.geom_type == "Polygon":
                centroid = geometry.centroid
            else:
                centroid = geometry

            batch.append((
                patch_uuid, label, image_id, computed_downsample,
                centroid.x, centroid.y, geometry.wkt, patch_bytes,
            ))

            if len(batch) >= _PATCH_BATCH_SIZE:
                patch_store.copy_insert(batch)
                total_patches += len(batch)
                batch.clear()

        if batch:
            patch_store.copy_insert(batch)
            total_patches += len(batch)

    # Move image to permanent storage after the DB session commits cleanly
    fsman.nas_write.move_to_permanent(session_id, project_id, image_id, image_filename)

    return {"image_id": image_id, "patch_count": total_patches}


# Concurrency note: https://github.com/ray-project/ray/issues/31879 
# For our use case, concurrency 1 is sufficient because the actor is only used for a single session at a time.
@ray.remote(max_concurrency=1)
class UploadSessionActor:
    """Per-session Ray actor that owns upload paths under the mounts directory
    and performs path validation before processing.

    Uses ``max_concurrency=2`` to allow ``process()`` to call ``ray.get()``
    on remote tasks without deadlocking the actor's single execution slot.
    """

    def __init__(self, project_id: int, session_id: str) -> None:
        self._project_id = project_id
        self._session_id = session_id
        self._fsman = FileStoreManager()
        self._fsman.upload_store.create_session_dirs(session_id)

        # Load project settings from the DB at actor startup
        with get_client().get_session() as session:
            self._settings = SettingsStore(session).get_all_as_dict(project_id=project_id)

    def __ray_shutdown__(self) -> None:
        try:
            self._fsman.upload_store.cleanup_session(self._session_id)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # File storage
    # ------------------------------------------------------------------

    def save_images(self, filenames: List[str], contents: List[bytes]) -> str:
        tmpdir = self._fsman.upload_store.get_session_dir(self._session_id)
        return _save_files(tmpdir, "images", filenames, contents)

    def save_masks(self, filenames: List[str], contents: List[bytes]) -> str:
        tmpdir = self._fsman.upload_store.get_session_dir(self._session_id)
        return _save_files(tmpdir, "masks", filenames, contents)

    def save_patch_csvs(self, filenames: List[str], contents: List[bytes]) -> str:
        tmpdir = self._fsman.upload_store.get_session_dir(self._session_id)
        return _save_files(tmpdir, "patch_csvs", filenames, contents)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_mixed(
        self,
        image_folder: str = "",
        mask_folder: str = "",
        patch_csv_folder: str = "",
    ) -> dict:
        tmpdir = self._fsman.upload_store.get_session_dir(self._session_id)
        return _validate_mixed(
            tmpdir,
            image_folder, mask_folder, patch_csv_folder,
        )

    def validate_image_csv(self, csv_content: bytes) -> dict:
        return _validate_image_csv(csv_content)

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process(self, paths: list[dict]) -> dict:
        """Dispatch process_row Ray tasks for each path.

        Returns the task_id and child task IDs without blocking on results.
        The caller should poll ray.state.state.list_tasks() with
        parent_task_id filter to track progress.
        """
        process_rows = [ProcessRow(**p) for p in paths]
        # Dispatch all tasks, passing pre-loaded settings
        task_refs = [
            process_row.remote(pr, self._project_id, self._session_id, self._settings)
            for pr in process_rows
        ]

        ray.get(task_refs)
        return
