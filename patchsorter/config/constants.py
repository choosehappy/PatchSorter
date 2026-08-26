import os

from enum import StrEnum


MOUNTS_PATH = os.path.join('/opt/PatchSorter', 'mounts')

# Maximum number of Ray tasks to return from the /task endpoint.
RAY_TASK_RETURN_LIMIT = 1000


class PredPatchSuffix(StrEnum):
    LATEST = "latest"
    LAST = "last"


class SettingType(StrEnum):
    ENUM = "enum"
    STRING = "string"
    BOOLEAN = "boolean"
    INTEGER = "integer"


class PatchExtractionMethod(StrEnum):
    USE_ESTIMATED_OBJECT_SIZE = "use estimated object size"
    USE_MANUAL_OBJECT_RADIUS = "use manual object radius"
    FIT_ALL_OBJECTS = "fit all objects"


IMAGE_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".svs", ".ndpi", ".vms", ".vmu", ".scn", ".mrxs"}
MASK_EXTS = {".geojson"}
PATCH_CSV_EXTS = {".csv"}

PATCH_BATCH_SIZE = 1000

UNASSIGNED_CLASS_ID = 1
