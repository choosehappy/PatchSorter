"""Unit tests for SettingsStore."""

import pytest

from patchsorter.config.constants import SettingType
from patchsorter.db.head_client import ProjectStore, SettingsStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project(db_session):
    """Create and return a project dict."""
    return ProjectStore(db_session).create("Test Project")


@pytest.fixture
def seeded_project(db_session, project):
    """Create a project and seed all project-scoped settings for it."""
    SettingsStore(db_session).seed_project_settings(project["project_id"])
    return project


@pytest.fixture
def seeded_app(db_session):
    """Seed all application-level settings."""
    SettingsStore(db_session).seed_app_settings()


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

def test_update_returns_setting_object(db_session, seeded_project):
    """update() returns a Setting with all columns populated."""
    pid = seeded_project["project_id"]
    store = SettingsStore(db_session)
    row = store.update("dl_num_workers", "16", project_id=pid)

    assert isinstance(row.setting_id, int)
    assert row.setting_key == "dl_num_workers"
    assert row.setting_value == "16"
    assert row.project_id == pid
    assert row.disabled is False


def test_update_changes_value(db_session, seeded_project):
    """update() overwrites setting_value with the new value."""
    pid = seeded_project["project_id"]
    store = SettingsStore(db_session)
    store.update("dl_patches_per_batch", "500", project_id=pid)
    row = store.get("dl_patches_per_batch", project_id=pid)
    assert row.setting_value == "500"


def test_update_skips_when_disabled(db_session, seeded_project):
    """update() does not change setting_value when the row is disabled."""
    pid = seeded_project["project_id"]
    store = SettingsStore(db_session)
    row = store.update("world_size", "8192", project_id=pid)
    assert row.setting_value == "4096"  # unchanged — world_size is disabled


def test_update_raises_for_missing_key(db_session, seeded_project):
    """update() raises KeyError when the setting row does not exist."""
    pid = seeded_project["project_id"]
    with pytest.raises(KeyError):
        SettingsStore(db_session).update("nonexistent_key", "val", project_id=pid)


def test_update_validates_value(db_session, seeded_project):
    """update() raises ValueError when the value fails schema validation."""
    pid = seeded_project["project_id"]
    with pytest.raises(ValueError):
        SettingsStore(db_session).update("dl_num_workers", "not_a_number", project_id=pid)


def test_update_app_level_setting(db_session, seeded_app):
    """update() with project_id=None updates an application-level setting."""
    store = SettingsStore(db_session)
    row = store.update("log_level", "DEBUG")
    assert row.project_id is None
    assert row.setting_value == "DEBUG"


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

def test_get_returns_none_for_missing_key(db_session):
    """get() returns None when no matching setting exists."""
    assert SettingsStore(db_session).get("nonexistent") is None


def test_get_returns_row_for_existing_key(db_session, seeded_project):
    """get() returns the Setting after seeding."""
    pid = seeded_project["project_id"]
    row = SettingsStore(db_session).get("dl_num_workers", project_id=pid)
    assert row is not None
    assert row.setting_value == "8"  # seeded default


def test_get_scoped_by_project_id(db_session, seeded_project):
    """get() with a project_id returns only the project-scoped setting."""
    pid = seeded_project["project_id"]
    store = SettingsStore(db_session)
    store.update("dl_num_workers", "32", project_id=pid)

    row = store.get("dl_num_workers", project_id=pid)
    assert row is not None
    assert row.setting_value == "32"


def test_get_project_setting_not_returned_without_project_id(db_session, seeded_project):
    """get() with project_id=None does not return a project-scoped setting."""
    pid = seeded_project["project_id"]
    # dl_num_workers exists for the project but not at app scope
    assert SettingsStore(db_session).get("dl_num_workers", project_id=None) is None


def test_get_app_setting_not_returned_for_project(db_session, seeded_app, seeded_project):
    """get() with a project_id does not return an application-level setting."""
    pid = seeded_project["project_id"]
    # log_level exists only at app scope
    assert SettingsStore(db_session).get("log_level", project_id=pid) is None


# ---------------------------------------------------------------------------
# list_by_project
# ---------------------------------------------------------------------------


def test_list_by_project_returns_all_in_scope(db_session, seeded_project):
    """list_by_project() returns every setting seeded for the project."""
    pid = seeded_project["project_id"]
    rows = SettingsStore(db_session).list_by_project(project_id=pid)
    keys = {r.setting_key for r in rows}
    assert {"dl_num_workers", "dl_patches_per_batch", "world_size", "agg_hierarchy_depth"}.issubset(keys)


def test_list_by_project_ordered_by_setting_id(db_session, seeded_project):
    """list_by_project() returns rows ordered by setting_id ascending."""
    pid = seeded_project["project_id"]
    rows = SettingsStore(db_session).list_by_project(project_id=pid)
    ids = [r.setting_id for r in rows]
    assert ids == sorted(ids)


def test_list_by_project_does_not_return_other_project(db_session):
    """list_by_project() for project A does not include project B settings."""
    store = SettingsStore(db_session)
    p_store = ProjectStore(db_session)
    project_a = p_store.create("Project A")
    project_b = p_store.create("Project B")
    pid_a = project_a["project_id"]
    pid_b = project_b["project_id"]
    store.seed_project_settings(pid_a)
    store.seed_project_settings(pid_b)

    rows = store.list_by_project(project_id=pid_a)
    assert all(r.project_id == pid_a for r in rows)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

def test_reset_returns_none_for_missing_key(db_session):
    """reset() returns None when the setting does not exist."""
    assert SettingsStore(db_session).reset("no_such_key") is None


def test_reset_restores_default_value(db_session, seeded_project):
    """reset() reverts setting_value to default_value after an update."""
    pid = seeded_project["project_id"]
    store = SettingsStore(db_session)
    store.update("dl_num_workers", "32", project_id=pid)

    row = store.reset("dl_num_workers", project_id=pid)
    assert row is not None
    assert row.setting_value == "8"  # back to seeded default


def test_reset_returns_unchanged_row_when_disabled(db_session, seeded_project):
    """reset() returns the row without modification when disabled=True."""
    pid = seeded_project["project_id"]
    store = SettingsStore(db_session)
    # world_size is disabled; reset() should return it but not raise
    row = store.reset("world_size", project_id=pid)
    assert row is not None
    assert row.disabled is True
    assert row.setting_value == "4096"


# ---------------------------------------------------------------------------
# reset_all
# ---------------------------------------------------------------------------


def test_reset_all_resets_all_settings_in_scope(db_session, seeded_project):
    """reset_all() reverts every setting to its default value."""
    pid = seeded_project["project_id"]
    store = SettingsStore(db_session)
    store.update("dl_num_workers", "32", project_id=pid)
    store.update("dl_patches_per_batch", "500", project_id=pid)

    rows = store.reset_all(project_id=pid)
    values = {r.setting_key: r.setting_value for r in rows}
    assert values["dl_num_workers"] == "8"
    assert values["dl_patches_per_batch"] == "10000"


def test_reset_all_includes_disabled_settings(db_session, seeded_project):
    """reset_all() includes disabled settings in the returned list."""
    pid = seeded_project["project_id"]
    rows = SettingsStore(db_session).reset_all(project_id=pid)
    keys = {r.setting_key for r in rows}
    assert "world_size" in keys
    assert "agg_hierarchy_depth" in keys



def test_reset_all_only_affects_given_scope(db_session):
    """reset_all() for a project scope does not touch settings in a different scope."""
    p_store = ProjectStore(db_session)
    project_a = p_store.create("Project A")
    project_b = p_store.create("Project B")
    pid_a = project_a["project_id"]
    pid_b = project_b["project_id"]
    store = SettingsStore(db_session)
    store.seed_project_settings(pid_a)
    store.seed_project_settings(pid_b)

    # Change a setting for project A only
    store.update("dl_num_workers", "32", project_id=pid_a)

    # Reset only project B
    store.reset_all(project_id=pid_b)

    # Project A's changed value should be unaffected
    row = store.get("dl_num_workers", project_id=pid_a)
    assert row.setting_value == "32"


# ---------------------------------------------------------------------------
# _validate_setting (static helper)
# ---------------------------------------------------------------------------

def _schema_for(key, setting_type, allowed_values=None):
    entry = {"type": setting_type}
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


def test_validate_setting_unknown_key_raises():
    """_validate_setting() raises KeyError for an unrecognised setting key."""
    schema = _schema_for("known_key", SettingType.STRING)
    with pytest.raises(KeyError):
        SettingsStore._validate_setting("unknown_key", "val", schema)


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
    assert entry["type"] == "integer"
    assert entry["default"] == "4096"
    assert entry["scope"] == "project"
