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

ANNOTATION_CLASS_COLOR_PALETTES: dict[str, list[str]] = {
    'default': [
        "#d5ff00", "#00ff00", "#ff937e", "#91d0cb",
        "#0000ff", "#00ae7e", "#ff00f6", "#5fad4e",
        "#01d0ff", "#bb8800", "#bdc6ff", "#008f9c",
        "#a5ffd2", "#ffa6fe", "#ffdb66", "#00ffc6",
        "#00b917", "#bdd393", "#004754", "#010067",
        "#0e4ca1", "#005f39", "#6b6882", "#683d3b",
        "#43002c", "#788231",
    ]
}
