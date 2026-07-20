from __future__ import annotations

import os
import shutil
from pathlib import Path

from patchsorter.config import constants


class FileStore:
    """Base class for managing paths with a configurable sub_path under the mounts root."""

    def __init__(self, sub_path: str) -> None:
        self.base_path: Path = Path(constants.MOUNTS_PATH)
        self.full_path: Path = self.base_path / sub_path

    def get_base_path(self) -> Path:
        return self.base_path

    def get_full_path(self, filepath: str | Path | None = None) -> Path:
        if filepath is None:
            return self.full_path
        return self.full_path / str(filepath)

    def global_to_relative(self, path: str | Path) -> str:
        """Convert an absolute path to a path relative to the mounts root (base_path)."""
        return os.path.relpath(path, self.base_path)

    def relative_to_global(self, path: str | Path) -> Path:
        """Convert a path relative to the mounts root (base_path) to an absolute path."""
        return self.base_path / str(path)

def scan_folder(folder_path: str | Path, valid_exts: set[str]) -> dict[str, Path]:
    """Scan *folder_path* for files with *valid_exts*.

    Args:
        folder_path: Absolute path to the directory to scan.
        valid_exts: Set of valid file extensions (e.g. ``{".tif", ".geojson"}``).

    Returns:
        Dict keyed by stem → Path. Empty dict if the folder doesn't exist.
    """
    folder = Path(folder_path)
    if not folder.is_dir():
        return {}
    result: dict[str, Path] = {}
    for f in folder.iterdir():
        if f.is_file() and f.suffix.lower() in valid_exts:
            result[f.stem] = f
    return result


class NASWriteStore(FileStore):
    """PatchSorter writable storage (uploaded files, projects, masks)."""

    def __init__(self) -> None:
        super().__init__("nas_write")

    def get_project_path(self, project_id: int) -> Path:
        return self.full_path / "projects" / f"proj_{project_id}"

    def get_project_image_path(self, project_id: int, image_id: int) -> Path:
        return self.get_project_path(project_id) / "images" / f"img_{image_id}"

    def get_project_mask_path(self, project_id: int, image_id: int) -> Path:
        return self.get_project_image_path(project_id, image_id) / "masks"

    def get_temp_path(self) -> Path:
        return self.full_path / "temp"

    def move_to_permanent(
        self,
        session_id: str,
        project_id: int,
        image_id: int,
        filename: str,
    ) -> Path:
        """Atomic move from UploadStore image path to permanent project storage."""
        upload_store = UploadStore()
        src = upload_store.get_images_dir(session_id) / filename
        dest_dir = self.get_project_image_path(project_id, image_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename
        shutil.move(src, dest)
        return dest


class NASReadStore(FileStore):
    """Read-only folder/CSV uploads mounted to the PatchSorter Docker container."""

    def __init__(self) -> None:
        super().__init__("nas_read")



class UploadStore(FileStore):
    """Per-upload-session temporary storage."""

    def __init__(self) -> None:
        super().__init__(Path("nas_write") / "upload_sessions")

    def get_session_dir(self, session_id: str) -> Path:
        return self.full_path / session_id

    def get_images_dir(self, session_id: str) -> Path:
        return self.get_session_dir(session_id) / "images"

    def get_masks_dir(self, session_id: str) -> Path:
        return self.get_session_dir(session_id) / "masks"

    def get_patch_csvs_dir(self, session_id: str) -> Path:
        return self.get_session_dir(session_id) / "patch_csvs"


    def create_session_dirs(self, session_id: str) -> None:
        """Create the images/, masks/, patch_csvs/ subdirs under the session dir."""
        session_dir = self.get_session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        self.get_images_dir(session_id).mkdir(exist_ok=True)
        self.get_masks_dir(session_id).mkdir(exist_ok=True)
        self.get_patch_csvs_dir(session_id).mkdir(exist_ok=True)

    def cleanup_session(self, session_id: str) -> None:
        """Remove the session directory tree."""
        session_dir = self.get_session_dir(session_id)
        shutil.rmtree(session_dir, ignore_errors=True)


class FileStoreManager:
    """Lightweight container for the three store instances."""

    def __init__(self) -> None:
        self.nas_write = NASWriteStore()
        self.nas_read = NASReadStore()
        self.upload = UploadStore()
