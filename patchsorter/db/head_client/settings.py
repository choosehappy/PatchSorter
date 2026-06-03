from __future__ import annotations

from functools import lru_cache
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy import or_

from patchsorter.db.head_client.models import Setting
from patchsorter.config.constants import SettingType

_SETTINGS_DEFAULTS_PATH = Path(__file__).parent.parent.parent / "config" / "settings_defaults.toml"


def _scope_clause(project_id: Optional[int]):
    """Return a WHERE clause fragment that matches the given project scope."""
    if project_id is None:
        return Setting.project_id.is_(None)
    return or_(Setting.project_id == project_id, Setting.project_id.is_(None))


class SettingsStore:
    """Data-access methods for the ``settings`` reference table.

    Settings are key/value pairs that can be scoped to an individual project
    (when ``project_id`` is provided) or applied at the application level
    (when ``project_id`` is ``None``).

    Args:
        session: An active SQLAlchemy Session provided by the application's
            session factory (SessionManager) — typically injected via FastAPI
            dependency injection.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def update(
        self,
        setting_key: str,
        setting_value: str,
        project_id: Optional[int] = None,
    ) -> Setting:
        """Update the value of an existing setting and return the ORM object.

        Assumes the setting row already exists (seeded via
        :meth:`seed_app_settings` or :meth:`seed_project_settings`).
        Raises if the row is not found.  Does not modify rows whose
        ``disabled`` flag is ``True``.

        The new *setting_value* is validated against the schema defined in
        ``settings_defaults.toml`` before being written.

        Args:
            setting_key: The key that identifies the setting.
            setting_value: The new value to store.
            project_id: The project scope, or ``None`` for an application-level
                setting.

        Returns:
            The updated :class:`~patchsorter.db.head_client.models.Setting` instance.

        Raises:
            KeyError: If *setting_key* is not present in the defaults schema or
                does not exist in the database for the given scope.
            ValueError: If *setting_value* fails type or enum validation.
        """
        obj = self._session.scalar(
            select(Setting)
            .where(Setting.setting_key == setting_key)
            .where(_scope_clause(project_id))
        )
        if obj is None:
            raise KeyError(
                f"Setting {setting_key!r} not found for project_id={project_id!r}. "
                "Seed project settings before calling update()."
            )
        schema = self._load_settings_schema()
        self._validate_setting(setting_key, setting_value, schema)
        if not obj.disabled:
            obj.setting_value = setting_value
        return obj
    
    def get_all_as_dict(self, project_id: Optional[int] = None) -> Dict[str, Any]:
        """Return all settings for the given scope as a dict of key to parsed value.

        The returned dict maps setting keys to their parsed values (e.g. integers
        for settings of type INTEGER, booleans for type BOOLEAN, etc.).  Settings
        with invalid values are skipped with a warning.

        Args:
            project_id: The project scope, or ``None`` for application-level
                settings.
        Returns:
            A dict mapping setting keys to their parsed values for the given scope.
        """
        rows = self.get_all_within_project_scope(project_id=project_id)
        result: Dict[str, Any] = {}
        for obj in rows:
            setting_type = SettingType(obj.setting_type)
            if setting_type == SettingType.INTEGER:
                value = int(obj.setting_value)
            elif setting_type == SettingType.BOOLEAN:
                value = obj.setting_value.lower() in ("true", "1")
            elif setting_type in (SettingType.ENUM, SettingType.STRING):
                value = obj.setting_value
            else:
                raise ValueError(f"Unsupported setting type: {setting_type}")
            result[obj.setting_key] = value
        return result

    def get(
        self,
        setting_key: str,
        project_id: Optional[int] = None,
    ) -> Optional[Setting]:
        """Fetch a single setting by key and optional project scope.

        Args:
            setting_key: The key that identifies the setting.
            project_id: The project scope, or ``None`` for an application-level
                setting.

        Returns:
            The :class:`~patchsorter.db.head_client.models.Setting` instance,
            or ``None`` if not found.
        """
        return self._session.scalar(
            select(Setting)
            .where(Setting.setting_key == setting_key)
            .where(_scope_clause(project_id))
        )
    
    # def get_value(
    #     self,
    #     setting_key: str,
    #     project_id: Optional[int],
    #     expected_type: type[T],
    # ) -> T:
    #     obj = self.get(setting_key, project_id)
    #     if obj is None:
    #         raise KeyError(
    #             f"Setting {setting_key!r} not found for project_id={project_id!r}."
    #         )

    #     raw_value = obj.setting_value
    #     setting_type = SettingType(obj.setting_type)

    #     if setting_type == SettingType.INTEGER:
    #         value = int(raw_value)
    #     elif setting_type == SettingType.BOOLEAN:
    #         value = raw_value.lower() in ("true", "1")
    #     elif setting_type in (SettingType.ENUM, SettingType.STRING):
    #         value = raw_value
    #     else:
    #         raise ValueError(f"Unsupported setting type: {setting_type}")

    #     if not isinstance(value, expected_type):
    #         raise TypeError(
    #             f"Setting {setting_key!r} expected {expected_type.__name__}, "
    #             f"got {type(value).__name__}"
    #         )
    #     return value  # type: ignore[return-value]


    def get_all_within_project_scope(self, project_id: Optional[int] = None) -> List[Setting]:
        """Return all settings for a given project scope, including application-level settings.

        Args:
            project_id: The project whose settings to return.  Pass ``None``
                to retrieve only application-level settings.

        Returns:
            A list of Setting ORM objects ordered by ``setting_id``.  Empty
            list if no settings exist for the given scope.
        """
        return list(
            self._session.scalars(
                select(Setting)
                .where(_scope_clause(project_id))
            ).all()
        )
        

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def seed_app_settings(self) -> None:
        """Insert all application-scoped defaults from ``settings_defaults.toml``.

        Inserts a row for each entry with ``scope = "application"`` if it does
        not already exist.  Existing rows are left untouched.
        """
        schema = SettingsStore._load_settings_schema()
        for key, meta in schema.items():
            if meta.get("scope") != "application":
                continue
            existing = self._session.scalar(
                select(Setting)
                .where(Setting.setting_key == key)
                .where(Setting.project_id.is_(None))
            )
            if existing is not None:
                continue
            allowed: Optional[str] = None
            if meta.get("type") == SettingType.ENUM:
                allowed = ",".join(meta["allowed_values"])
            self._session.add(Setting(
                project_id=None,
                setting_key=key,
                setting_value=meta["default"],
                default_value=meta["default"],
                setting_type=SettingType(meta["type"]),
                allowed_values=allowed,
                disabled=meta.get("disabled", False),
            ))

    def seed_project_settings(self, project_id: int) -> None:
        """Insert all project-scoped defaults from ``settings_defaults.toml``.

        Inserts a row for each entry with ``scope = "project"`` if it does not
        already exist for the given *project_id*.  Existing rows are left
        untouched.

        Args:
            project_id: The integer ID of the project to seed settings for.
        """
        schema = SettingsStore._load_settings_schema()
        for key, meta in schema.items():
            if meta.get("scope") != "project":
                continue
            existing = self._session.scalar(
                select(Setting)
                .where(Setting.setting_key == key)
                .where(Setting.project_id == project_id)
            )
            if existing is not None:
                continue
            allowed: Optional[str] = None
            if meta.get("type") == SettingType.ENUM:
                allowed = ",".join(meta["allowed_values"])
            self._session.add(Setting(
                project_id=project_id,
                setting_key=key,
                setting_value=meta["default"],
                default_value=meta["default"],
                setting_type=SettingType(meta["type"]),
                allowed_values=allowed,
                disabled=meta.get("disabled", False),
            ))

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_settings_schema() -> Dict[str, Any]:
        """Load and return the settings schema from the defaults TOML file.

        Returns:
            The ``settings`` table from ``settings_defaults.toml`` — a dict
            keyed by setting name, each value being a dict with at least
            ``scope``, ``default``, and ``type`` fields.

        Raises:
            FileNotFoundError: If the defaults file cannot be found.
            tomllib.TOMLDecodeError: If the file is not valid TOML.
        """
        with _SETTINGS_DEFAULTS_PATH.open("rb") as fh:
            data = tomllib.load(fh)
        return data["settings"]

    @staticmethod
    def _validate_setting(key: str, value: str, schema: Dict[str, Any]) -> None:
        """Validate *value* for *key* against the loaded schema.

        Args:
            key: The setting key to validate.
            value: The candidate string value.
            schema: The full schema dict returned by :meth:`_load_settings_schema`.

        Raises:
            KeyError: If *key* is not present in the schema.
            ValueError: If *value* does not satisfy the type or allowed-values
                constraints defined for *key*.
        """
        if key not in schema:
            raise KeyError(f"Unknown setting: {key!r}")

        entry = schema[key]
        setting_type = SettingType(entry["type"])

        if setting_type == SettingType.INTEGER:
            try:
                int(value)
            except ValueError:
                raise ValueError(
                    f"Setting {key!r} expects an integer value, got {value!r}"
                )
        elif setting_type == SettingType.BOOLEAN:
            if value.lower() not in ("true", "false", "1", "0"):
                raise ValueError(
                    f"Setting {key!r} expects a boolean value ('true'/'false'), got {value!r}"
                )
        elif setting_type == SettingType.ENUM:
            allowed = entry.get("allowed_values", [])
            if value not in allowed:
                raise ValueError(
                    f"Setting {key!r} must be one of {allowed}, got {value!r}"
                )
        # SettingType.STRING accepts any value — no further validation needed

    def reset(
        self,
        setting_key: str,
        project_id: Optional[int] = None,
    ) -> Optional[Setting]:
        """Reset a setting to its stored default value.

        The default value is read from the ``default_value`` column of the
        existing row (which was populated from ``settings_defaults.toml`` at
        seed time).  The candidate default is validated against the schema
        before being written.

        Disabled settings cannot be reset and are returned unchanged.

        Args:
            setting_key: The key of the setting to reset.
            project_id: The project scope, or ``None`` for an application-level
                setting.

        Returns:
            The (possibly updated) :class:`~patchsorter.db.head_client.models.Setting`
            instance, or ``None`` if no matching row exists.
        """
        obj = self._session.scalar(
            select(Setting)
            .where(Setting.setting_key == setting_key)
            .where(_scope_clause(project_id))
        )
        if obj is None:
            return None
        if not obj.disabled:
            obj.setting_value = obj.default_value
        return obj

    def reset_all(
        self,
        project_id: Optional[int] = None,
    ) -> List[Setting]:
        """Reset all settings for the given scope to their default values.

        Unlike :meth:`reset`, this method resets **all** settings including
        those with ``disabled = TRUE``.  Each default value is validated
        against the schema before any rows are written; if any validation
        fails the method raises without modifying the database.

        Args:
            project_id: The project scope, or ``None`` for application-level
                settings.

        Returns:
            A list of :class:`~patchsorter.db.head_client.models.Setting` instances
            reflecting the state after the reset, ordered by ``setting_id``.
            Empty list if no settings exist for the given scope.
        """
        rows = self.get_all_within_project_scope(project_id=project_id)
        if not rows:
            return []
        for obj in rows:
            obj.setting_value = obj.default_value
        return rows
