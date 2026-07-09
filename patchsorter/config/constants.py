import os

from enum import StrEnum


MOUNTS_PATH = os.path.join('/opt/PatchSorter', 'mounts')


class PredPatchSuffix(StrEnum):
    LATEST = "latest"
    LAST = "last"


class SettingType(StrEnum):
    ENUM = "enum"
    STRING = "string"
    BOOLEAN = "boolean"
    INTEGER = "integer"
