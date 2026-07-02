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


def _validate_paths(tmpdir: str, paths: list[dict]) -> dict:
    """Validate uploaded filenames against the session temp directory.

    ``paths`` is a list of ``{type, filename}`` dicts (PathItem).
    Files are paired by positional index within each type group.
    """
    images_dir = os.path.join(tmpdir, "images")
    masks_dir = os.path.join(tmpdir, "masks")
    labels_dir = os.path.join(tmpdir, "labels")

    image_names = [p["filename"] for p in paths if p["type"] == "image"]
    mask_names = [p["filename"] for p in paths if p["type"] == "mask"]
    label_names = [p["filename"] for p in paths if p["type"] == "csv"]

    rows: list[dict] = []
    for i, img_name in enumerate(image_names):
        mask_name = mask_names[i] if i < len(mask_names) else ""
        label_name = label_names[i] if i < len(label_names) else ""

        img_path = os.path.join(images_dir, img_name)
        mask_path = os.path.join(masks_dir, mask_name) if mask_name else ""
        label_path = os.path.join(labels_dir, label_name) if label_name else ""

        errors: list[str] = []
        if not os.path.exists(img_path):
            errors.append(f"Image not found: {img_name}")
        if mask_name and not os.path.exists(mask_path):
            errors.append(f"Mask not found: {mask_name}")
        if label_name and not os.path.exists(label_path):
            errors.append(f"Label not found: {label_name}")

        rows.append(
            dict(
                image=img_path,
                mask=mask_path,
                csv=label_path,
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
    label_folder: str = "",
) -> dict:
    """Enumerate server-side image folder and match masks/labels by filename stem."""
    img_dir = Path(image_folder) if image_folder else None
    mask_dir = Path(mask_folder) if mask_folder else None
    label_dir = Path(label_folder) if label_folder else None

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

    if label_dir and not label_dir.is_dir():
        return {
            "paths": [
                dict(
                    image="",
                    mask="",
                    csv="",
                    status="error",
                    error=f"Label folder not found or not a directory: {label_folder}",
                )
            ],
            "errors": 1,
        }

    image_files = sorted(
        f for f in img_dir.iterdir() if f.suffix.lower() in _IMAGE_EXTS
    )

    rows: list[dict] = []
    for img_file in image_files:
        stem = img_file.stem
        mask_path = ""
        label_path = ""

        if mask_dir and mask_dir.is_dir():
            candidate = mask_dir / f"{stem}.geojson"
            if candidate.exists():
                mask_path = str(candidate)

        if label_dir and label_dir.is_dir():
            candidate = label_dir / f"{stem}.csv"
            if candidate.exists():
                label_path = str(candidate)

        rows.append(
            dict(
                image=str(img_file),
                mask=mask_path,
                csv=label_path,
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


def _validate_csv(csv_content: bytes) -> dict:
    """Parse a CSV file list and validate that each path exists on the server."""
    text = csv_content.decode("utf-8-sig")  # handle BOM
    reader = csv.DictReader(io.StringIO(text))

    rows: list[dict] = []
    for row in reader:
        img = (row.get("image") or "").strip()
        mask = (row.get("mask") or "").strip()
        label = (row.get("label") or "").strip()

        errors: list[str] = []
        if img and not os.path.exists(img):
            errors.append(f"Image not found: {img}")
        if mask and not os.path.exists(mask):
            errors.append(f"Mask not found: {mask}")
        if label and not os.path.exists(label):
            errors.append(f"Label not found: {label}")

        rows.append(
            dict(
                image=img,
                mask=mask,
                csv=label,
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
        for subdir in ("images", "masks", "labels"):
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

    def save_labels(self, filenames: List[str], contents: List[bytes]) -> str:
        return _save_files(self._tmpdir.name, "labels", filenames, contents)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_paths(self, paths: list[dict]) -> dict:
        return _validate_paths(self._tmpdir.name, paths)

    def validate_folders(
        self,
        image_folder: str,
        mask_folder: str = "",
        label_folder: str = "",
    ) -> dict:
        return _validate_folders(self._tmpdir.name, image_folder, mask_folder, label_folder)

    def validate_csv(self, csv_content: bytes) -> dict:
        return _validate_csv(csv_content)

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
