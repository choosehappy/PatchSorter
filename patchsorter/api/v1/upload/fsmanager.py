from __future__ import annotations

import os
import shutil

from patchsorter.config import constants


class FileStore:
    """Base class for managing paths with a configurable sub_path under the mounts root."""

    def __init__(self, sub_path: str) -> None:
        self.base_path = constants.MOUNTS_PATH
        self.full_path = os.path.join(self.base_path, sub_path)

    def get_base_path(self) -> str:
        return self.base_path

    def get_full_path(self, filepath: str | None = None) -> str:
        if filepath is None:
            return self.full_path
        return os.path.join(self.full_path, filepath)

    def global_to_relative(self, path: str) -> str:
        """Convert an absolute path to a path relative to the mounts root (base_path)."""
        return os.path.relpath(path, self.base_path)

    def relative_to_global(self, path: str) -> str:
        """Convert a path relative to the mounts root (base_path) to an absolute path."""
        return os.path.join(self.base_path, path)


class NASWriteStore(FileStore):
    """PatchSorter writable storage (uploaded files, projects, masks)."""

    def __init__(self) -> None:
        super().__init__("nas_write")

    def get_project_path(self, project_id: int) -> str:
        return os.path.join(self.full_path, "projects", f"proj_{project_id}")

    def get_project_image_path(self, project_id: int, image_id: int) -> str:
        return os.path.join(self.get_project_path(project_id), "images", f"img_{image_id}")

    def get_project_mask_path(self, project_id: int, image_id: int) -> str:
        return os.path.join(self.get_project_image_path(project_id, image_id), "masks")

    def get_temp_path(self) -> str:
        return os.path.join(self.full_path, "temp")

    def move_to_permanent(
        self,
        session_id: str,
        project_id: int,
        image_id: int,
        filename: str,
    ) -> str:
        """Atomic move from UploadStore image path to permanent project storage."""
        upload_store = UploadStore()
        src = os.path.join(upload_store.get_images_dir(session_id), filename)
        dest_dir = self.get_project_image_path(project_id, image_id)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, filename)
        shutil.move(src, dest)
        return dest


class NASReadStore(FileStore):
    """Read-only folder/CSV uploads mounted to the PatchSorter Docker container."""

    def __init__(self) -> None:
        super().__init__("nas_read")

    def get_input_images_path(self) -> str:
        return os.path.join(self.full_path, "images")

    def get_input_masks_dir(self) -> str:
        return os.path.join(self.full_path, "masks")


class UploadStore(FileStore):
    """Per-upload-session temporary storage."""

    def __init__(self) -> None:
        super().__init__(os.path.join("nas_write", "tmp", "upload_sessions"))

    def get_session_dir(self, session_id: str) -> str:
        return os.path.join(self.full_path, session_id)

    def get_images_dir(self, session_id: str) -> str:
        return os.path.join(self.get_session_dir(session_id), "images")

    def get_masks_dir(self, session_id: str) -> str:
        return os.path.join(self.get_session_dir(session_id), "masks")

    def get_patch_csvs_dir(self, session_id: str) -> str:
        return os.path.join(self.get_session_dir(session_id), "patch_csvs")

    def get_image_path(self, session_id: str, filename: str) -> str:
        return os.path.join(self.get_images_dir(session_id), filename)

    def get_mask_path(self, session_id: str, filename: str) -> str:
        return os.path.join(self.get_masks_dir(session_id), filename)

    def get_patch_csv_path(self, session_id: str, filename: str) -> str:
        return os.path.join(self.get_patch_csvs_dir(session_id), filename)

    def create_session_dirs(self, session_id: str) -> None:
        """Create the images/, masks/, patch_csvs/ subdirs under the session dir."""
        session_dir = self.get_session_dir(session_id)
        os.makedirs(session_dir, exist_ok=True)
        os.makedirs(self.get_images_dir(session_id), exist_ok=True)
        os.makedirs(self.get_masks_dir(session_id), exist_ok=True)
        os.makedirs(self.get_patch_csvs_dir(session_id), exist_ok=True)

    def cleanup_session(self, session_id: str) -> None:
        """Remove the session directory tree."""
        session_dir = self.get_session_dir(session_id)
        shutil.rmtree(session_dir, ignore_errors=True)


class FileStoreManager:
    """Lightweight container for the three store instances."""

    def __init__(self) -> None:
        self.nas_write = NASWriteStore()
        self.nas_read = NASReadStore()
        self.upload_store = UploadStore()
