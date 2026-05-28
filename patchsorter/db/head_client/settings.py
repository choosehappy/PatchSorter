from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from patchsorter.config.constants import SettingType

_SETTINGS_DEFAULTS_PATH = Path(__file__).parent.parent.parent / "config" / "settings_defaults.toml"


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

    def upsert(
        self,
        setting_key: str,
        setting_value: str,
        default_value: str,
        setting_type: SettingType,
        project_id: Optional[int] = None,
        allowed_values: Optional[str] = None,
        disabled: bool = False,
    ) -> Dict[str, Any]:
        """Insert or update a setting and return the resulting row.

        If a row with the same (*setting_key*, *project_id*) combination
        already exists and is not disabled, its ``setting_value`` is updated
        in-place.  If the existing row has ``disabled = TRUE`` the value is
        not changed.

        Args:
            setting_key: The key that identifies the setting.
            setting_value: The new value for the setting.
            default_value: The default value used when the setting is reset.
            setting_type: One of :attr:`~patchsorter.config.constants.SettingType`.
            project_id: The project this setting belongs to, or ``None`` for
                an application-level setting.
            allowed_values: Comma-separated (or JSON) list of valid values;
                required when *setting_type* is ``'enum'``.
            disabled: Pass ``True`` to mark the setting as read-only after the
                initial insert.

        Returns:
            A dict with all columns of the upserted row.
        """
        row = self._session.execute(
            text(
                """
                INSERT INTO settings
                    (project_id, setting_key, setting_value, default_value,
                     setting_type, allowed_values, disabled)
                VALUES
                    (:project_id, :key, :value, :default_value,
                     :setting_type, :allowed_values, :disabled)
                ON CONFLICT ON CONSTRAINT uq_project_setting
                DO UPDATE SET setting_value = EXCLUDED.setting_value
                    WHERE NOT settings.disabled
                RETURNING *
                """
            ),
            {
                "project_id": project_id,
                "key": setting_key,
                "value": setting_value,
                "default_value": default_value,
                "setting_type": setting_type,
                "allowed_values": allowed_values,
                "disabled": disabled,
            },
        ).mappings().one_or_none()
        if row is None:
            # The ON CONFLICT DO UPDATE WHERE NOT disabled clause was false —
            # the existing row is disabled and its value was intentionally
            # preserved.  Return the current row unchanged.
            return self.get(setting_key, project_id=project_id)
        return dict(row)

    def get(
        self,
        setting_key: str,
        project_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Fetch a single setting by key and optional project scope.

        Args:
            setting_key: The key that identifies the setting.
            project_id: The project scope, or ``None`` for an application-level
                setting.

        Returns:
            A dict with all setting columns, or ``None`` if not found.
        """
        row = self._session.execute(
            text(
                """
                SELECT * FROM settings
                WHERE setting_key = :key
                  AND (project_id = :project_id OR (project_id IS NULL AND :project_id IS NULL))
                """
            ),
            {"key": setting_key, "project_id": project_id},
        ).mappings().one_or_none()
        return dict(row) if row else None

    def list_by_project(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Return all settings for a given project scope.

        Args:
            project_id: The project whose settings to return.  Pass ``None``
                to retrieve application-level settings.

        Returns:
            A list of dicts ordered by ``setting_id``.  Empty list if no
            settings exist for the given scope.
        """
        rows = self._session.execute(
            text(
                """
                SELECT * FROM settings
                WHERE (project_id = :project_id OR (project_id IS NULL AND :project_id IS NULL))
                ORDER BY setting_id
                """
            ),
            {"project_id": project_id},
        ).mappings().all()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def seed_app_settings(self) -> None:
        """Upsert all application-scoped defaults from ``settings_defaults.toml``.

        Reads every entry with ``scope = "application"`` and calls
        :meth:`upsert` for each one.  Safe to call multiple times — existing
        non-disabled rows have their value refreshed; disabled rows are left
        untouched.
        """
        schema = SettingsStore._load_settings_schema()
        for key, meta in schema.items():
            if meta.get("scope") != "application":
                continue
            allowed: Optional[str] = None
            if meta.get("type") == SettingType.ENUM:
                allowed = ",".join(meta["allowed_values"])
            self.upsert(
                setting_key=key,
                setting_value=meta["default"],
                default_value=meta["default"],
                setting_type=SettingType(meta["type"]),
                project_id=None,
                allowed_values=allowed,
                disabled=meta.get("disabled", False),
            )

    def seed_project_settings(self, project_id: int) -> None:
        """Upsert all project-scoped defaults from ``settings_defaults.toml``.

        Reads every entry with ``scope = "project"`` and calls :meth:`upsert`
        for each one using the given *project_id*.  Safe to call multiple
        times — existing non-disabled rows have their value refreshed; disabled
        rows are left untouched.

        Args:
            project_id: The integer ID of the project to seed settings for.
        """
        schema = SettingsStore._load_settings_schema()
        for key, meta in schema.items():
            if meta.get("scope") != "project":
                continue
            allowed: Optional[str] = None
            if meta.get("type") == SettingType.ENUM:
                allowed = ",".join(meta["allowed_values"])
            self.upsert(
                setting_key=key,
                setting_value=meta["default"],
                default_value=meta["default"],
                setting_type=SettingType(meta["type"]),
                project_id=project_id,
                allowed_values=allowed,
                disabled=meta.get("disabled", False),
            )

    @staticmethod
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
    ) -> Optional[Dict[str, Any]]:
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
            A dict with all columns of the (possibly updated) row, or ``None``
            if no matching row exists.

        Raises:
            KeyError: If *setting_key* is not present in the defaults schema.
            ValueError: If the stored default value fails type/enum validation.
        """
        row = self.get(setting_key, project_id=project_id)
        if row is None:
            return None

        schema = self._load_settings_schema()
        self._validate_setting(setting_key, row["default_value"], schema)

        updated = self._session.execute(
            text(
                """
                UPDATE settings
                SET setting_value = default_value
                WHERE setting_key = :key
                  AND (project_id = :project_id OR (project_id IS NULL AND :project_id IS NULL))
                  AND NOT disabled
                RETURNING *
                """
            ),
            {"key": setting_key, "project_id": project_id},
        ).mappings().one_or_none()

        # If disabled, return the row as-is (no update was made)
        return dict(updated) if updated is not None else row

    def reset_all(
        self,
        project_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Reset all settings for the given scope to their default values.

        Unlike :meth:`reset`, this method resets **all** settings including
        those with ``disabled = TRUE``.  Each default value is validated
        against the schema before any rows are written; if any validation
        fails the method raises without modifying the database.

        Args:
            project_id: The project scope, or ``None`` for application-level
                settings.

        Returns:
            A list of dicts (one per row) reflecting the state after the
            reset, ordered by ``setting_id``.  Empty list if no settings
            exist for the given scope.

        Raises:
            KeyError: If any setting key is not present in the defaults schema.
            ValueError: If any stored default value fails type/enum validation.
        """
        rows = self.list_by_project(project_id=project_id)
        if not rows:
            return []

        schema = self._load_settings_schema()
        for row in rows:
            self._validate_setting(row["setting_key"], row["default_value"], schema)

        updated = self._session.execute(
            text(
                """
                UPDATE settings
                SET setting_value = default_value
                WHERE (project_id = :project_id OR (project_id IS NULL AND :project_id IS NULL))
                RETURNING *
                """
            ),
            {"project_id": project_id},
        ).mappings().all()

        return [dict(r) for r in updated]
