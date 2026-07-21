from __future__ import annotations

import csv
import io
import os
import uuid
from pathlib import Path
from typing import List
import ray
import large_image

from patchsorter.config.constants import IMAGE_EXTS, MASK_EXTS, PATCH_CSV_EXTS, PATCH_BATCH_SIZE
from patchsorter.utils.fsmanager import FileStoreManager, scan_folder
from patchsorter.api.v1.upload.models import ProcessRow
from patchsorter.api.v1.upload.patch_iterator import (
    CsvGeometryIterable,
    GeojsonGeometryIterable,
    HybridPatchIterable,
    GeometryIterable,
    create_patch_iterator,
)
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

# ------------------------------------------------------------------
# Core logic extracted into plain functions for testability.
# The actor delegates to these; tests call them directly with a tmpdir.
# ------------------------------------------------------------------

def _save_files(tmpdir: str | Path, subdir: str, filenames: List[str], contents: List[bytes]) -> str:
    """Save files to *subdir* inside *tmpdir*. Returns a count message."""
    dest = Path(tmpdir) / subdir
    dest.mkdir(parents=True, exist_ok=True)
    for name, data in zip(filenames, contents):
        with open(dest / os.path.basename(name), "wb") as f:
            f.write(data)
    return f"Uploaded {len(filenames)} {subdir.rstrip('s')}(s)"


def _resolve_path(fsman, relative_path: str, session_id: str) -> Path:
    """Resolve a relative path to absolute, detecting session vs nas_read source."""
    if relative_path.startswith(f"{session_id}/"):
        path = fsman.upload.get_full_path(relative_path)
    else:
        path = fsman.nas_read.relative_to_global(relative_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {relative_path} (resolved to {path})")
    return path


def _validate_mixed(
    session_id: str,
    image_folder: str | None = None,
    mask_folder: str | None = None,
    patch_csv_folder: str | None = None,
) -> dict:
    """Glob all available files from the session dir and optional server folders, returning a row per image."""

    fsman = FileStoreManager()

    # Define sources to scan.
    sources = [
        ("image", fsman.upload.get_images_dir(session_id), image_folder, IMAGE_EXTS),
        ("mask", fsman.upload.get_masks_dir(session_id), mask_folder, MASK_EXTS),
        ("patch CSV", fsman.upload.get_patch_csvs_dir(session_id), patch_csv_folder, PATCH_CSV_EXTS),
    ]

    results: dict[str, dict[str, Path]] = {}

    for label, session_dir, server_folder, exts in sources:
        merged: dict[str, Path] = {}

        # SCAN SESSION TEMP DIR
        if session_dir.is_dir():
            merged.update(scan_folder(session_dir, exts))

        # SCAN OPTIONAL SERVER FOLDER
        if server_folder is not None:
            folder_fullpath = fsman.nas_read.relative_to_global(server_folder)
            server_files = scan_folder(folder_fullpath, exts)

            if not server_files:
                raise Exception(f"No valid {label} files found in {label} folder: {server_folder}")

            merged.update(server_files)

        results[label] = merged

    images, masks, csvs = results["image"], results["mask"], results["patch CSV"]
            
    if not images:
        return {
            "paths": [
                dict(image=None, mask=None, csv=None, status="error",
                     error="No images found in session temp dir or image_folder"),
            ],
            "errors": 1,
        }

    upload_base = fsman.upload.get_full_path()
    rows: list[dict] = []

    for stem in sorted(images):
        img_path = images[stem]
        stem = img_path.stem
        img_rel = _make_relative(img_path, fsman, upload_base, session_id)
        mask_rel = _make_relative(masks[stem], fsman, upload_base, session_id) if stem in masks else None
        csv_rel = _make_relative(csvs[stem], fsman, upload_base, session_id) if stem in csvs else None

        try:
            ts = large_image.open(str(img_path))
            base_mag = ts.getMetadata().get("magnification")
        except Exception:
            base_mag = None

        has_data = bool(mask_rel or csv_rel)
        rows.append(dict(
            image=img_rel,
            mask=mask_rel,
            csv=csv_rel,
            status="ok" if has_data else "error",
            error=None if has_data else f"No mask or patch CSV found for {img_path.name}",
            base_mag=base_mag,
        ))

    return {"paths": rows, "errors": sum(1 for r in rows if r["status"] == "error")}


def _make_relative(path: Path, fsman: FileStoreManager, upload_base: Path, session_id: str) -> str:
    """Return a relative path string, prefixed with *session_id* if the file lives in the upload store."""
    try:
        path.relative_to(upload_base)
        return os.path.relpath(path, upload_base)
    except ValueError:
        return fsman.nas_read.global_to_relative(path)


def _validate_image_csv(csv_content: bytes, session_id: str = "") -> dict:
    """Parse an image manifest CSV and validate that each path exists on the server."""
    text = csv_content.decode("utf-8-sig")  # handle BOM
    reader = csv.DictReader(io.StringIO(text))

    fsman = FileStoreManager()
    rows: list[dict] = []
    for row in reader:
        img = (row.get("image") or "").strip()
        mask = (row.get("mask") or "").strip()
        patch_csv = (row.get("patch_csv") or "").strip()

        errors: list[str] = []
        if img:
            img_full = fsman.nas_read.relative_to_global(img)
            if not img_full.exists():
                errors.append(f"Image not found: {img}")
            else:
                try:
                    ts = large_image.open(str(img_full))
                    base_mag = ts.getMetadata().get("magnification")
                except Exception:
                        base_mag = None

        if mask and not fsman.nas_read.relative_to_global(mask).exists():
            errors.append(f"Mask not found: {mask}")
        if patch_csv and not fsman.nas_read.relative_to_global(patch_csv).exists():
            errors.append(f"Patch CSV not found: {patch_csv}")

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
            dict(image=None, mask=None, csv=None, status="error", error="CSV file contains no data rows")
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

    # Resolve paths: ProcessRow paths may be relative to the session temp dir or to nas_read; resolve to absolute paths.
    image_path = _resolve_path(fsman, process_row_arg.image, session_id)
    image_filename = image_path.name
    mask_path = _resolve_path(fsman, process_row_arg.mask, session_id) if process_row_arg.mask else None
    csv_path = _resolve_path(fsman, process_row_arg.csv, session_id) if process_row_arg.csv else None

    # Open image tile source
    ts = large_image.open(str(image_path))

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

    # Get patch iterator based on available mask and/or CSV
    iterator: GeometryIterable = create_patch_iterator(mask_path, csv_path)

    # Load settings (passed from UploadSessionActor — no extra DB round-trip needed)
    patch_size: int = int(settings.get("patch_size", 64))
    patch_extraction_method: str = settings.get("patch_extraction_method", "use estimated object size")
    object_radius_str: str | None = settings.get("object_radius")
    object_radius: float | None = float(object_radius_str) if object_radius_str else None

    # Determine downsample strategy
    mm_per_pixel = mm_per_pixel_at_base(base_mag)

    if patch_extraction_method == "use manual object radius": # TODO: compare setting with an enum.
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
            image_path=str(image_path),
            base_mag=base_mag,
            base_width=base_width,
            base_height=base_height,
            deepzoom_tilesize=deepzoom_tilesize,
        )
        image_id = result["image_id"]

        patch_store = PatchStore(project_id, session)
        batch: list[tuple] = []
        total_patches = 0

        for geometry, label, patch_uuid in iterator:
            if per_patch_downsample:
                radius_pixels = get_polygon_radius_in_pixels(geometry)
                radius_microns = radius_pixels * mm_per_pixel * 1000
                computed_downsample = compute_downsample_factor(radius_microns, base_mag, patch_size, mm_per_pixel)
            else:
                computed_downsample = downsample

            patch_bytes = extract_patch_from_geometry(ts, geometry, patch_size, computed_downsample, base_mag)

            if geometry.geom_type == "Polygon":
                centroid = geometry.centroid
            elif geometry.geom_type == "Point":
                centroid = geometry
            else:
                raise ValueError(f"Unsupported geometry type: {geometry.geom_type}")

            batch.append((
                patch_uuid, label, image_id, computed_downsample,
                centroid.x, centroid.y, geometry.wkt, patch_bytes,
            ))

            if len(batch) >= PATCH_BATCH_SIZE:
                patch_store.copy_insert(batch)
                total_patches += len(batch)
                batch.clear()

        if batch:
            patch_store.copy_insert(batch)
            total_patches += len(batch)

    # Move image to permanent storage after the DB session commits cleanly
    if process_row_arg.image.startswith(f"{session_id}/"):
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
        self._fsman.upload.create_session_dirs(session_id)

        # Load project settings from the DB at actor startup
        with get_client().get_session() as session:
            self._settings = SettingsStore(session).get_all_as_dict(project_id=project_id)

    def __ray_shutdown__(self) -> None:
        try:
            self._fsman.upload.cleanup_session(self._session_id)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # File storage
    # ------------------------------------------------------------------

    def save_images(self, filenames: List[str], contents: List[bytes]) -> str:
        tmpdir = self._fsman.upload.get_session_dir(self._session_id)
        return _save_files(tmpdir, "images", filenames, contents)

    def save_masks(self, filenames: List[str], contents: List[bytes]) -> str:
        tmpdir = self._fsman.upload.get_session_dir(self._session_id)
        return _save_files(tmpdir, "masks", filenames, contents)

    def save_patch_csvs(self, filenames: List[str], contents: List[bytes]) -> str:
        tmpdir = self._fsman.upload.get_session_dir(self._session_id)
        return _save_files(tmpdir, "patch_csvs", filenames, contents)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_mixed(
        self,
        image_folder: str | None = None,
        mask_folder: str | None = None,
        patch_csv_folder: str | None = None,
    ) -> dict:
        return _validate_mixed(self._session_id, image_folder, mask_folder, patch_csv_folder)

    def validate_image_csv(self, csv_content: bytes) -> dict:
        return _validate_image_csv(csv_content, self._session_id)

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
            process_row
                .options(name=f"Import {pr.image}")
                .remote(pr, self._project_id, self._session_id, self._settings)
            for pr in process_rows
        ]

        ray.get(task_refs)
        return
