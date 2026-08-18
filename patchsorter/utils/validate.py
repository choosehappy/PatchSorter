from pathvalidate import validate_filepath
from pathlib import PurePath


def validate_path(value: str) -> str:
    validate_filepath(
        value,
        additional_reserved_names=[".", ".."],
    )

    # Otherwise pathlib joins will treat the path as absolute and ignore the base path.
    if PurePath(value).is_absolute():
        raise ValueError("Absolute paths are not allowed")

    return value