from enum import StrEnum


class PredPatchSuffix(StrEnum):
    LATEST = "latest"
    LAST = "last"


class SettingType(StrEnum):
    ENUM = "enum"
    STRING = "string"
    BOOLEAN = "boolean"
    INTEGER = "integer"


UNASSIGNED_LABEL_CLASS_ID = -1
"""Reserved ``label_class_id`` for the "Unassigned" class.  Cannot be deleted."""
