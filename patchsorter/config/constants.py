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


IMAGE_EXTS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".svs", ".ndpi", ".vms", ".vmu", ".scn", ".mrxs", ".tif.gz"}
MASK_EXTS = {".geojson"}
PATCH_CSV_EXTS = {".csv"}

PATCH_BATCH_SIZE = 1000

UNASSIGNED_CLASS_ID = 1

class PatchCSVColumns(StrEnum):
    PATCH_ID = "patch_id"
    PATCH_UID = "patch_uid"
    LABEL_CLASS_ID = "label_class_id"
    CENTROID_X = "centroid_x"
    CENTROID_Y = "centroid_y"


class PatchGeoJSONProperties(StrEnum):
    LABEL = "label"
    CLASS_ID = "class_id"
    LABEL_CLASS_ID = "label_class_id"
    UID = "uid"

class LargeImageMetadataKeys(StrEnum):
    IMAGE_WIDTH = "sizeX"
    IMAGE_HEIGHT = "sizeY"
    TILE_WIDTH = "tileWidth"
    BASE_MAGNIFICATION = "magnification"