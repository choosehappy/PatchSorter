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
