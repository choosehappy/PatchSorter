from __future__ import annotations

import csv
import io
import os
import tempfile
import uuid
from pathlib import Path
from typing import List
from ray.actor import exit_actor
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
        if img_dir.is_dir():
            for f in img_dir.iterdir():
                if f.suffix.lower() in _IMAGE_EXTS:
                    image_stems[f.stem] = f

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
        if mf.is_dir():
            for f in mf.iterdir():
                if f.suffix.lower() == ".geojson":
                    mask_by_stem[f.stem] = f

    # Gather patch_csvs from all sources
    csv_by_stem: dict[str, Path] = {}
    if patch_csvs_dir.is_dir():
        for f in patch_csvs_dir.iterdir():
            if f.suffix.lower() == ".csv":
                csv_by_stem[f.stem] = f
    if patch_csv_folder:
        pf = Path(patch_csv_folder)
        if pf.is_dir():
            for f in pf.iterdir():
                if f.suffix.lower() == ".csv":
                    csv_by_stem[f.stem] = f

    rows: list[dict] = []
    for stem in sorted(image_stems.keys()):
        img_path = image_stems[stem]
        mask_path = str(mask_by_stem[stem]) if stem in mask_by_stem else ""
        csv_path = str(csv_by_stem[stem]) if stem in csv_by_stem else ""

        if not mask_path and not csv_path:
            rows.append(
                dict(
                    image=str(img_path),
                    mask=mask_path,
                    csv=csv_path,
                    status="error",
                    error=f"No mask or patch CSV found for {img_path.name}",
                )
            )
        else:
            rows.append(
                dict(
                    image=str(img_path),
                    mask=mask_path,
                    csv=csv_path,
                    status="ok",
                    error="",
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


    def __ray_shutdown__(self) -> None:
        try:
            # Explicitly clean up the temporary directory when the actor is killed. Python gc will also clean it up eventually.
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

    def validate_mixed(
        self,
        image_folder: str = "",
        mask_folder: str = "",
        patch_csv_folder: str = "",
    ) -> dict:
        return _validate_mixed(
            self._tmpdir.name,
            image_folder, mask_folder, patch_csv_folder,
        )

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
            exit_actor() # terminate the actor after processing has completed.
