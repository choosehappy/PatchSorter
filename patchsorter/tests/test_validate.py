"""Unit tests for :func:`~patchsorter.utils.validate.validate_path`."""

import pytest

from pathvalidate.error import ValidationError

from patchsorter.utils.validate import validate_path


class TestValidatePathValid:
    def test_simple_relative_path(self):
        """validate_path() accepts simple relative paths."""
        assert validate_path("data/images") == "data/images"

    def test_path_with_leading_dot_slash(self):
        """validate_path() accepts paths starting with './'."""
        assert validate_path("./data/images") == "./data/images"

    def test_path_with_tilde(self):
        """validate_path() accepts paths starting with '~'."""
        assert validate_path("~/data/images") == "~/data/images"

    def test_path_with_file_extension(self):
        """validate_path() accepts paths with file extensions."""
        assert validate_path("slides/sample.svs") == "slides/sample.svs"

    def test_path_with_numbers_and_underscores(self):
        """validate_path() accepts paths with alphanumeric chars and underscores."""
        assert validate_path("slide_001/tile_42.tif") == "slide_001/tile_42.tif"

    def test_single_segment_path(self):
        """validate_path() accepts single-segment paths."""
        assert validate_path("file.txt") == "file.txt"

    def test_path_with_spaces(self):
        """validate_path() accepts paths with spaces."""
        assert validate_path("my slides/sample.svs") == "my slides/sample.svs"


class TestValidatePathInvalid:
    def test_empty_string_raises(self):
        """validate_path() raises ValidationError for empty string."""
        with pytest.raises(ValidationError):
            validate_path("")

    def test_absolute_path_raises_validation_error(self):
        """validate_path() raises ValidationError for absolute paths."""
        with pytest.raises(ValidationError):
            validate_path("/absolute/path/to/file")

    def test_absolute_path_with_drive_raises(self):
        """validate_path() raises ValidationError for Windows-style absolute paths."""
        with pytest.raises(ValidationError):
            validate_path("C:\\Users\\file")

    def test_current_dir_rejected(self):
        """validate_path() rejects '.' as a reserved name."""
        with pytest.raises(Exception):
            validate_path(".")

    def test_parent_dir_rejected(self):
        """validate_path() rejects '..' as a reserved name."""
        with pytest.raises(Exception):
            validate_path("..")

    def test_nested_absolute_path_raises(self):
        """validate_path() raises ValidationError for paths that resolve to absolute."""
        with pytest.raises(ValidationError):
            validate_path("/tmp/file")
