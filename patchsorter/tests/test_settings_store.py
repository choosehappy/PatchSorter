"""Unit tests for SettingsStore."""

import pytest

from patchsorter.config.constants import SettingType, SettingScope
from patchsorter.db.head_client import ProjectStore, SettingsStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project(db_session):
    """Create and return a project dict."""
    return ProjectStore(db_session).create("Test Project")


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

def test_update_raises_for_disabled_setting(db_session, seeded_project):
    """update() raises SettingDisabledError when the setting is disabled."""
    pid = seeded_project["project_id"]
    with pytest.raises(Exception, match="read-only"):
        SettingsStore(db_session).update("world_size", "8192", project_id=pid)


def test_update_raises_for_missing_key(db_session, seeded_project):
    """update() raises KeyError when the setting key does not exist."""
    pid = seeded_project["project_id"]
    with pytest.raises(KeyError):
        SettingsStore(db_session).update("nonexistent_key", "val", project_id=pid)


def test_update_raises_for_invalid_value(db_session, seeded_project):
    """update() raises ValueError when the value fails schema validation."""
    pid = seeded_project["project_id"]
    with pytest.raises(ValueError):
        SettingsStore(db_session).update("dl_num_workers", "not_a_number", project_id=pid)


def test_update_app_level_setting(db_session):
    """update() with project_id=None updates an application-level setting."""
    store = SettingsStore(db_session)
    store.update("log_level", "DEBUG")
    result = store.get_str("log_level")
    assert result == "DEBUG"


def test_update_validates_enum_value(db_session):
    """update() raises ValueError for invalid enum value."""
    with pytest.raises(ValueError, match="log_level"):
        SettingsStore(db_session).update("log_level", "INVALID")


def test_update_validates_boolean_value():
    """update() raises ValueError for invalid boolean string via _validate_setting."""
    schema = _schema_for("flag", SettingType.BOOLEAN)
    with pytest.raises(ValueError, match="boolean"):
        SettingsStore._validate_setting("flag", "maybe", schema)


# ---------------------------------------------------------------------------
# get_str / get_int / get_bool
# ---------------------------------------------------------------------------

def test_get_str_raises_for_missing_key(db_session):
    """get_str() raises KeyError when no matching setting exists in schema."""
    with pytest.raises(KeyError):
        SettingsStore(db_session).get_str("nonexistent_key")


def test_get_int_returns_default_for_project(db_session, project):
    """get_int() returns the schema default when no override exists."""
    pid = project["project_id"]
    result = SettingsStore(db_session).get_int("dl_num_workers", project_id=pid)
    assert result == 1


def test_get_int_returns_override(db_session, project):
    """get_int() returns the override value when it exists."""
    pid = project["project_id"]
    store = SettingsStore(db_session)
    store.update("dl_num_workers", "32", project_id=pid)
    result = store.get_int("dl_num_workers", project_id=pid)
    assert result == 32


def test_get_int_raises_type_mismatch(db_session):
    """get_int() raises SettingTypeMismatchError for non-INTEGER settings."""
    with pytest.raises(TypeError, match="string"):
        SettingsStore(db_session).get_int("log_level")


def test_get_str_returns_app_level_default(db_session):
    """get_str() returns app-level setting default."""
    result = SettingsStore(db_session).get_str("log_level")
    assert result == "INFO"


def test_get_str_scoped_by_project(db_session, project):
    """get_str() with project_id returns project-scoped setting."""
    pid = project["project_id"]
    store = SettingsStore(db_session)
    store.update("dl_patches_per_batch", "500", project_id=pid)
    result = store.get_int("dl_patches_per_batch", project_id=pid)
    assert result == 500


def test_get_bool_returns_default(db_session):
    """get_bool() returns the schema default for BOOLEAN settings."""
    result = SettingsStore(db_session).get_bool("flag")
    assert result is False


def test_get_bool_returns_override(db_session):
    """get_bool() returns the override value for BOOLEAN settings."""
    store = SettingsStore(db_session)
    store.update("flag", "true")
    result = store.get_bool("flag")
    assert result is True


# ---------------------------------------------------------------------------
# get_raw / get_all_raw
# ---------------------------------------------------------------------------

def test_get_raw_returns_resolved_setting(db_session, project):
    """get_raw() returns a ResolvedSetting with schema metadata and value."""
    pid = project["project_id"]
    result = SettingsStore(db_session).get_raw("dl_num_workers", project_id=pid)
    assert result.key == "dl_num_workers"
    assert result.value == "1"
    assert result.type == SettingType.INTEGER
    assert result.default == "1"
    assert result.project_id == pid


def test_get_raw_app_level_returns_null_project_id(db_session):
    """get_raw() for app-level setting returns None project_id."""
    result = SettingsStore(db_session).get_raw("log_level")
    assert result.key == "log_level"
    assert result.project_id is None


def test_get_raw_raises_for_missing_key(db_session):
    """get_raw() raises KeyError for unknown setting key."""
    with pytest.raises(KeyError):
        SettingsStore(db_session).get_raw("nonexistent")


def test_get_all_raw_returns_all_settings(db_session, project):
    """get_all_raw() returns every setting in scope with resolved values."""
    pid = project["project_id"]
    result = SettingsStore(db_session).get_all_raw(project_id=pid, scope=SettingScope.PROJECT)
    assert isinstance(result, dict)
    assert "dl_num_workers" in result
    assert "dl_patches_per_batch" in result
    assert result["dl_num_workers"].value == "1"
    assert result["dl_num_workers"].project_id == pid


def test_get_all_raw_includes_app_level(db_session, project):
    """get_all_raw() with project_id includes app-level settings as fallback."""
    pid = project["project_id"]
    result = SettingsStore(db_session).get_all_raw(project_id=pid)
    assert "log_level" in result
    assert result["log_level"].project_id is None


def test_get_all_raw_with_scope_filter(db_session):
    """get_all_raw() with scope filter returns only matching settings."""
    result = SettingsStore(db_session).get_all_raw(scope=SettingScope.APPLICATION)
    assert "log_level" in result
    assert result["log_level"].project_id is None
    assert "dl_num_workers" not in result


# ---------------------------------------------------------------------------
# get_definition
# ---------------------------------------------------------------------------

def test_get_definition_returns_schema_entry(db_session):
    """get_definition() returns the SettingDef schema entry."""
    result = SettingsStore(db_session).get_definition("world_size")
    assert result.key == "world_size"
    assert result.type == SettingType.INTEGER
    assert result.default == "4096"
    assert result.scope == SettingScope.PROJECT
    assert result.disabled is True


def test_get_definition_raises_for_missing_key(db_session):
    """get_definition() raises KeyError for unknown setting key."""
    with pytest.raises(KeyError):
        SettingsStore(db_session).get_definition("nonexistent")


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

def test_reset_no_op_when_no_override(db_session, project):
    """reset() is a no-op when no override exists."""
    pid = project["project_id"]
    store = SettingsStore(db_session)
    store.reset("dl_num_workers", project_id=pid)
    result = store.get_int("dl_num_workers", project_id=pid)
    assert result == 1  # still the default


def test_reset_reverts_to_default(db_session, project):
    """reset() reverts setting to its schema default."""
    pid = project["project_id"]
    store = SettingsStore(db_session)
    store.update("dl_num_workers", "32", project_id=pid)
    store.reset("dl_num_workers", project_id=pid)
    result = store.get_int("dl_num_workers", project_id=pid)
    assert result == 1


# ---------------------------------------------------------------------------
# reset_all
# ---------------------------------------------------------------------------

def test_reset_all_reverts_all_overrides(db_session, project):
    """reset_all() reverts every setting to its schema default."""
    pid = project["project_id"]
    store = SettingsStore(db_session)
    store.update("dl_num_workers", "32", project_id=pid)
    store.update("dl_patches_per_batch", "500", project_id=pid)
    store.reset_all(project_id=pid)
    assert store.get_int("dl_num_workers", project_id=pid) == 1
    assert store.get_int("dl_patches_per_batch", project_id=pid) == 1024


def test_reset_all_with_scope_filter(db_session, project):
    """reset_all() with scope only resets settings in that scope."""
    pid = project["project_id"]
    store = SettingsStore(db_session)
    store.update("log_level", "DEBUG")
    store.update("dl_num_workers", "16", project_id=pid)
    store.reset_all(scope=SettingScope.APPLICATION)
    # App-level setting reset
    assert store.get_str("log_level") == "INFO"
    # Project-level setting unchanged
    assert store.get_int("dl_num_workers", project_id=pid) == 16


# ---------------------------------------------------------------------------
# _validate_setting (static helper)
# ---------------------------------------------------------------------------

def _schema_for(key, setting_type, allowed_values=None):
    entry = {"type": setting_type, "scope": SettingScope.APPLICATION}
    if allowed_values is not None:
        entry["allowed_values"] = allowed_values
    return {key: entry}


def test_validate_setting_integer_valid():
    """_validate_setting() does not raise for a valid integer string."""
    schema = _schema_for("count", SettingType.INTEGER)
    SettingsStore._validate_setting("count", "42", schema)


def test_validate_setting_integer_invalid():
    """_validate_setting() raises ValueError for a non-integer string."""
    schema = _schema_for("count", SettingType.INTEGER)
    with pytest.raises(ValueError, match="integer"):
        SettingsStore._validate_setting("count", "not_an_int", schema)


def test_validate_setting_boolean_valid(request):
    """_validate_setting() accepts all recognised boolean string forms."""
    schema = _schema_for("flag", SettingType.BOOLEAN)
    for val in ("true", "false", "True", "False", "1", "0"):
        SettingsStore._validate_setting("flag", val, schema)


def test_validate_setting_boolean_invalid():
    """_validate_setting() raises ValueError for an unrecognised boolean string."""
    schema = _schema_for("flag", SettingType.BOOLEAN)
    with pytest.raises(ValueError, match="boolean"):
        SettingsStore._validate_setting("flag", "yes", schema)


def test_validate_setting_enum_valid():
    """_validate_setting() does not raise when the value is in allowed_values."""
    schema = _schema_for("theme", SettingType.ENUM, allowed_values=["light", "dark"])
    SettingsStore._validate_setting("theme", "dark", schema)


def test_validate_setting_enum_invalid():
    """_validate_setting() raises ValueError when the value is not in allowed_values."""
    schema = _schema_for("theme", SettingType.ENUM, allowed_values=["light", "dark"])
    with pytest.raises(ValueError):
        SettingsStore._validate_setting("theme", "neon", schema)


def test_validate_setting_string_accepts_any_value():
    """_validate_setting() does not raise for STRING type regardless of value."""
    schema = _schema_for("description", SettingType.STRING)
    SettingsStore._validate_setting("description", "anything goes!", schema)


# ---------------------------------------------------------------------------
# _load_settings_schema (static helper)
# ---------------------------------------------------------------------------

def test_load_settings_schema_returns_expected_keys():
    """_load_settings_schema() returns a dict containing the canonical setting keys."""
    schema = SettingsStore._load_settings_schema()
    assert isinstance(schema, dict)
    assert "world_size" in schema
    assert "agg_hierarchy_depth" in schema


def test_load_settings_schema_world_size_entry():
    """The 'world_size' entry from the TOML file has the expected structure."""
    schema = SettingsStore._load_settings_schema()
    entry = schema["world_size"]
    assert entry.type == SettingType.INTEGER
    assert entry.default == "4096"
    assert entry.scope == SettingScope.PROJECT


def test_load_settings_schema_contains_app_settings():
    """_load_settings_schema() includes application-scoped settings."""
    schema = SettingsStore._load_settings_schema()
    assert "log_level" in schema
    assert schema["log_level"].scope == SettingScope.APPLICATION
