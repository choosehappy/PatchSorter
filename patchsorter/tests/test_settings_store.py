"""Unit tests for SettingsStore."""

import pytest

from patchsorter.config.constants import SettingType
from patchsorter.db.head_client import ProjectStore, SettingsStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upsert_string(store: SettingsStore, key: str, value: str = "val", project_id=None, **kw):
    return store.upsert(
        setting_key=key,
        setting_value=value,
        default_value=value,
        setting_type=SettingType.STRING,
        project_id=project_id,
        **kw,
    )


def _upsert_enum(
    store: SettingsStore,
    key: str,
    value: str = "light",
    default_value: str = "light",
    allowed_values: str = "light,dark,system",
    project_id=None,
    **kw,
):
    return store.upsert(
        setting_key=key,
        setting_value=value,
        default_value=default_value,
        setting_type=SettingType.ENUM,
        allowed_values=allowed_values,
        project_id=project_id,
        **kw,
    )


# ---------------------------------------------------------------------------
# upsert
# ---------------------------------------------------------------------------

def test_upsert_returns_expected_fields(db_session):
    """upsert() returns a dict containing all expected setting columns."""
    store = SettingsStore(db_session)
    row = _upsert_string(store, "my_key", "my_val")

    assert isinstance(row["setting_id"], int)
    assert row["setting_key"] == "my_key"
    assert row["setting_value"] == "my_val"
    assert row["default_value"] == "my_val"
    assert row["setting_type"] == SettingType.STRING
    assert row["project_id"] is None
    assert row["disabled"] is False


def test_upsert_app_level_setting(db_session):
    """upsert() with project_id=None creates an application-level setting."""
    row = _upsert_string(SettingsStore(db_session), "app_setting", project_id=None)
    assert row["project_id"] is None


def test_upsert_project_level_setting(db_session):
    """upsert() with a project_id creates a project-scoped setting."""
    project = ProjectStore(db_session).create("Project Setting Test")
    project_id = project["project_id"]
    row = _upsert_string(SettingsStore(db_session), "proj_setting", project_id=project_id)
    assert row["project_id"] == project_id


def test_upsert_updates_existing_row(db_session):
    """A second upsert() with the same key overwrites setting_value."""
    store = SettingsStore(db_session)
    _upsert_string(store, "color", "red")
    updated = _upsert_string(store, "color", "blue")
    assert updated["setting_value"] == "blue"


def test_upsert_skips_update_when_disabled(db_session):
    """upsert() does not change setting_value when the row is disabled.

    A non-NULL project_id is used so the unique constraint (project_id,
    setting_key) fires correctly on the second upsert.
    """
    project = ProjectStore(db_session).create("Disabled Test")
    pid = project["project_id"]
    store = SettingsStore(db_session)
    _upsert_string(store, "locked_key", "original", project_id=pid, disabled=True)
    result = _upsert_string(store, "locked_key", "changed", project_id=pid)
    assert result["setting_value"] == "original"


def test_upsert_with_allowed_values(db_session):
    """upsert() stores allowed_values for enum settings."""
    row = _upsert_enum(SettingsStore(db_session), "theme")
    assert row["allowed_values"] == "light,dark,system"


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

def test_get_returns_none_for_missing_key(db_session):
    """get() returns None when no matching setting exists."""
    assert SettingsStore(db_session).get("nonexistent") is None


def test_get_returns_row_for_existing_key(db_session):
    """get() returns the setting dict after a successful upsert."""
    store = SettingsStore(db_session)
    _upsert_string(store, "fetch_me", "the_value")
    row = store.get("fetch_me")
    assert row is not None
    assert row["setting_value"] == "the_value"


def test_get_scoped_by_project_id(db_session):
    """get() with a project_id returns only the project-scoped setting."""
    project = ProjectStore(db_session).create("Scoped Get Test")
    project_id = project["project_id"]
    store = SettingsStore(db_session)
    _upsert_string(store, "scoped", "proj_val", project_id=project_id)

    row = store.get("scoped", project_id=project_id)
    assert row is not None
    assert row["setting_value"] == "proj_val"


def test_get_does_not_return_wrong_scope(db_session):
    """get() with project_id=None does not return a project-scoped setting."""
    project = ProjectStore(db_session).create("Scope Isolation Test")
    project_id = project["project_id"]
    _upsert_string(SettingsStore(db_session), "scoped_only", project_id=project_id)

    assert SettingsStore(db_session).get("scoped_only", project_id=None) is None


def test_get_app_level_does_not_return_project_setting(db_session):
    """Querying an app-level key with a project_id returns None."""
    project = ProjectStore(db_session).create("App Level Test")
    project_id = project["project_id"]
    _upsert_string(SettingsStore(db_session), "app_only", project_id=None)

    assert SettingsStore(db_session).get("app_only", project_id=project_id) is None


# ---------------------------------------------------------------------------
# list_by_project
# ---------------------------------------------------------------------------

def test_list_by_project_empty(db_session):
    """list_by_project() returns an empty list when no settings exist."""
    assert SettingsStore(db_session).list_by_project() == []


def test_list_by_project_returns_all_in_scope(db_session):
    """list_by_project() returns every setting inserted for the given scope."""
    store = SettingsStore(db_session)
    _upsert_string(store, "k1")
    _upsert_string(store, "k2")

    rows = store.list_by_project(project_id=None)
    keys = {r["setting_key"] for r in rows}
    assert {"k1", "k2"}.issubset(keys)


def test_list_by_project_ordered_by_setting_id(db_session):
    """list_by_project() returns rows ordered by setting_id ascending."""
    store = SettingsStore(db_session)
    _upsert_string(store, "a_key")
    _upsert_string(store, "b_key")

    rows = store.list_by_project(project_id=None)
    ids = [r["setting_id"] for r in rows]
    assert ids == sorted(ids)


def test_list_by_project_does_not_return_other_project(db_session):
    """list_by_project() for project A does not include project B settings."""
    store = SettingsStore(db_session)
    p_store = ProjectStore(db_session)
    project = p_store.create("Project A")
    project_id = project["project_id"]
    _upsert_string(store, "proj_key", project_id=project_id)
    _upsert_string(store, "app_key", project_id=None)

    rows = store.list_by_project(project_id=project_id)
    assert all(r["project_id"] == project_id for r in rows)
    assert not any(r["setting_key"] == "app_key" for r in rows)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------

def test_reset_returns_none_for_missing_key(db_session):
    """reset() returns None when the setting does not exist."""
    assert SettingsStore(db_session).reset("no_such_key") is None


def test_reset_restores_default_value(db_session):
    """reset() reverts setting_value to default_value.

    A non-NULL project_id is used so the unique constraint fires correctly
    on the second upsert (which changes the value before the reset).
    """
    project = ProjectStore(db_session).create("Reset Test")
    pid = project["project_id"]
    store = SettingsStore(db_session)
    store.upsert(
        setting_key="theme",
        setting_value="light",
        default_value="light",
        setting_type=SettingType.ENUM,
        allowed_values="light,dark,system",
        project_id=pid,
    )
    store.upsert(
        setting_key="theme",
        setting_value="dark",
        default_value="light",
        setting_type=SettingType.ENUM,
        allowed_values="light,dark,system",
        project_id=pid,
    )

    row = store.reset("theme", project_id=pid)
    assert row is not None
    assert row["setting_value"] == "light"


def test_reset_returns_unchanged_row_when_disabled(db_session):
    """reset() returns the existing row without modification when disabled=True."""
    store = SettingsStore(db_session)
    store.upsert(
        setting_key="world_size",
        setting_value="8192",
        default_value="4096",
        setting_type=SettingType.INTEGER,
        disabled=True,
    )

    row = store.reset("world_size")
    assert row is not None
    assert row["setting_value"] == "8192"


# ---------------------------------------------------------------------------
# reset_all
# ---------------------------------------------------------------------------

def test_reset_all_returns_empty_list_when_no_settings(db_session):
    """reset_all() returns an empty list when the scope has no settings."""
    assert SettingsStore(db_session).reset_all(project_id=None) == []


def test_reset_all_resets_all_settings_in_scope(db_session):
    """reset_all() reverts every setting in the scope to its default.

    Only keys present in settings_defaults.toml are used so that the schema
    validation inside reset_all() does not raise KeyError.
    """
    store = SettingsStore(db_session)
    store.upsert(
        setting_key="theme",
        setting_value="dark",
        default_value="light",
        setting_type=SettingType.ENUM,
        allowed_values="light,dark,system",
    )
    store.upsert(
        setting_key="world_size",
        setting_value="8192",
        default_value="4096",
        setting_type=SettingType.INTEGER,
    )

    rows = store.reset_all(project_id=None)
    values = {r["setting_key"]: r["setting_value"] for r in rows}
    assert values["theme"] == "light"
    assert values["world_size"] == "4096"


def test_reset_all_includes_disabled_settings(db_session):
    """reset_all() also resets disabled settings (unlike reset())."""
    store = SettingsStore(db_session)
    store.upsert(
        setting_key="world_size",
        setting_value="8192",
        default_value="4096",
        setting_type=SettingType.INTEGER,
        disabled=True,
    )

    rows = store.reset_all(project_id=None)
    values = {r["setting_key"]: r["setting_value"] for r in rows}
    assert values["world_size"] == "4096"


def test_reset_all_only_affects_given_scope(db_session):
    """reset_all() for a project scope does not touch app-level settings.

    Uses schema-known keys (theme, world_size) so reset_all's validation passes.
    """
    project = ProjectStore(db_session).create("Scope Test")
    project_id = project["project_id"]
    store = SettingsStore(db_session)

    store.upsert("theme", "dark", "light", SettingType.ENUM, project_id=None, allowed_values="light,dark,system")
    store.upsert("world_size", "8192", "4096", SettingType.INTEGER, project_id=project_id)

    store.reset_all(project_id=project_id)

    app_row = store.get("theme", project_id=None)
    assert app_row["setting_value"] == "dark"


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
    assert "theme" in schema
    assert "world_size" in schema
    assert "agg_hierarchy_depth" in schema


def test_load_settings_schema_theme_entry():
    """The 'theme' entry from the TOML file has the expected structure."""
    schema = SettingsStore._load_settings_schema()
    theme = schema["theme"]
    assert theme["type"] == "enum"
    assert theme["default"] == "light"
    assert "light" in theme["allowed_values"]
    assert "dark" in theme["allowed_values"]
