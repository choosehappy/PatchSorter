from __future__ import annotations

import csv
import io
import os
import tempfile
import uuid
from pathlib import Path
from typing import List

import ray

_IMAGE_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}


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


def _validate_paths(tmpdir: str, image_names: List[str], mask_names: List[str], patch_csv_names: List[str]) -> dict:
    """Validate uploaded filenames against the session temp directory."""
    images_dir = os.path.join(tmpdir, "images")
    masks_dir = os.path.join(tmpdir, "masks")
    patch_csvs_dir = os.path.join(tmpdir, "patch_csvs")

    rows: list[dict] = []
    for i, img_name in enumerate(image_names):
        mask_name = mask_names[i] if i < len(mask_names) else ""
        patch_csv_name = patch_csv_names[i] if i < len(patch_csv_names) else ""

        img_path = os.path.join(images_dir, img_name)
        mask_path = os.path.join(masks_dir, mask_name) if mask_name else ""
        patch_csv_path = os.path.join(patch_csvs_dir, patch_csv_name) if patch_csv_name else ""

        errors: list[str] = []
        if not os.path.exists(img_path):
            errors.append(f"Image not found: {img_name}")
        if mask_name and not os.path.exists(mask_path):
            errors.append(f"Mask not found: {mask_name}")
        if patch_csv_name and not os.path.exists(patch_csv_path):
            errors.append(f"Patch CSV not found: {patch_csv_name}")

        rows.append(
            dict(
                image=img_path,
                mask=mask_path,
                csv=patch_csv_path,
                status="error" if errors else "ok",
                error="; ".join(errors),
            )
        )

    if not rows:
        rows.append(
            dict(image="", mask="", csv="", status="error", error="No image paths provided")
        )

    return {"paths": rows, "errors": sum(1 for r in rows if r["status"] == "error")}


def _validate_folders(
    tmpdir: str,
    image_folder: str,
    mask_folder: str = "",
    patch_csv_folder: str = "",
) -> dict:
    """Enumerate server-side image folder and match masks/patch_csvs by filename stem."""
    img_dir = Path(image_folder) if image_folder else None
    mask_dir = Path(mask_folder) if mask_folder else None
    patch_csv_dir = Path(patch_csv_folder) if patch_csv_folder else None

    if img_dir is None or not img_dir.is_dir():
        return {
            "paths": [
                dict(
                    image="",
                    mask="",
                    csv="",
                    status="error",
                    error=f"Image folder not found or not a directory: {image_folder}",
                )
            ],
            "errors": 1,
        }

    if mask_dir and not mask_dir.is_dir():
        return {
            "paths": [
                dict(
                    image="",
                    mask="",
                    csv="",
                    status="error",
                    error=f"Mask folder not found or not a directory: {mask_folder}",
                )
            ],
            "errors": 1,
        }

    if patch_csv_dir and not patch_csv_dir.is_dir():
        return {
            "paths": [
                dict(
                    image="",
                    mask="",
                    csv="",
                    status="error",
                    error=f"Patch CSV folder not found or not a directory: {patch_csv_folder}",
                )
            ],
            "errors": 1,
        }

    # upper case extensions are allowed
    image_files = sorted(
        f for f in img_dir.iterdir() if f.suffix.lower() in _IMAGE_EXTS
    )

    rows: list[dict] = []
    for img_file in image_files:
        stem = img_file.stem
        mask_path = ""
        patch_csv_path = ""

        if mask_dir and mask_dir.is_dir():
            candidate = mask_dir / f"{stem}.geojson"
            if candidate.exists():
                mask_path = str(candidate)

        if patch_csv_dir and patch_csv_dir.is_dir():
            candidate = patch_csv_dir / f"{stem}.csv"
            if candidate.exists():
                patch_csv_path = str(candidate)

        rows.append(
            dict(
                image=str(img_file),
                mask=mask_path,
                csv=patch_csv_path,
                status="ok",
                error="",
            )
        )

    if not rows:
        rows.append(
            dict(
                image="",
                mask="",
                csv="",
                status="error",
                error=f"No image files found in: {image_folder}",
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
        if img and not os.path.exists(img):
            errors.append(f"Image not found: {img}")
        if mask and not os.path.exists(mask):
            errors.append(f"Mask not found: {mask}")
        if patch_csv and not os.path.exists(patch_csv):
            errors.append(f"Patch CSV not found: {patch_csv}")

        rows.append(
            dict(
                image=img,
                mask=mask,
                csv=patch_csv,
                status="error" if errors else "ok",
                error="; ".join(errors),
            )
        )

    if not rows:
        rows.append(
            dict(image="", mask="", csv="", status="error", error="CSV file contains no data rows")
        )

    return {"paths": rows, "errors": sum(1 for r in rows if r["status"] == "error")}


@ray.remote(max_concurrency=1)
class UploadSessionActor:
    """Per-session Ray actor that owns a temporary directory for uploaded files
    and performs path validation before processing.

    Uses ``max_concurrency=1`` to serialise all calls within a session.
    """

    def __init__(self, project_id: int, session_id: str) -> None:
        self._project_id = project_id
        self._session_id = session_id
        self._tmpdir = tempfile.TemporaryDirectory(prefix=f"ps_upload_{session_id}_")
        for subdir in ("images", "masks", "patch_csvs"):
            os.makedirs(os.path.join(self._tmpdir.name, subdir), exist_ok=True)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Delete the temporary directory and all uploaded files."""
        try:
            self._tmpdir.cleanup()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # File storage
    # ------------------------------------------------------------------

    def save_images(self, filenames: List[str], contents: List[bytes]) -> str:
        return _save_files(self._tmpdir.name, "images", filenames, contents)

    def save_masks(self, filenames: List[str], contents: List[bytes]) -> str:
        return _save_files(self._tmpdir.name, "masks", filenames, contents)

    def save_patch_csvs(self, filenames: List[str], contents: List[bytes]) -> str:
        return _save_files(self._tmpdir.name, "patch_csvs", filenames, contents)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_paths(self, image_names: List[str], mask_names: List[str], patch_csv_names: List[str]) -> dict:
        return _validate_paths(self._tmpdir.name, image_names, mask_names, patch_csv_names)

    def validate_folders(
        self,
        image_folder: str,
        mask_folder: str = "",
        patch_csv_folder: str = "",
    ) -> dict:
        return _validate_folders(self._tmpdir.name, image_folder, mask_folder, patch_csv_folder)

    def validate_image_csv(self, csv_content: bytes) -> dict:
        return _validate_image_csv(csv_content)

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process(self, paths: list[dict]) -> dict:
        """Start processing for validated paths.

        TODO: dispatch actual Ray tasks (image ingestion, patch extraction, etc.)
        """
        task_id = str(uuid.uuid4())
        try:
            return {
                "task_id": task_id,
                "status": "pending",
                "message": f"Processing {len(paths)} entr{'y' if len(paths) == 1 else 'ies'}",
            }
        finally:
            self.cleanup()
