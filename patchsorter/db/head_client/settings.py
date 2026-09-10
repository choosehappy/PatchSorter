from __future__ import annotations

from functools import lru_cache
import tomllib
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from patchsorter.db.head_client.models import SettingOverride
from patchsorter.config.constants import SettingType

_SETTINGS_DEFAULTS_PATH = Path(__file__).parent.parent.parent / "config" / "settings_defaults.toml"


class SettingDisabledError(Exception):
    """Raised when attempting to modify a setting marked disabled in the schema."""


class SettingTypeMismatchError(TypeError):
    """Raised when a typed accessor (get_int, get_bool, ...) is called on a
    setting whose schema type doesn't match."""


class SettingDef(BaseModel):
    """Static schema definition for one setting, loaded from settings_defaults.toml.

    This is a config-layer object, not a persistence-layer one — it has no
    corresponding database row and is never written to the database. It's
    recomputed once per process (see `_load_settings_schema`) directly from
    the TOML file. Compare with `SettingOverride`, the SQLAlchemy model that
    stores a single project's (or the application's) deviation from the
    default described here.
    """

    key: str
    scope: str
    type: SettingType
    default: str
    allowed_values: Optional[List[str]] = None
    disabled: bool = False

    @model_validator(mode="after")
    def _check_enum_has_values(self) -> "SettingDef":
        if self.type == SettingType.ENUM and not self.allowed_values:
            raise ValueError(f"{self.key}: enum type requires allowed_values")
        return self


class ResolvedSetting(SettingDef):
    """A `SettingDef` plus the setting's current effective value.

    Returned by the raw-value accessors (`get_raw`, `get_all_raw`,
    `_resolve_raw`) so callers get both the schema metadata (type, scope,
    default, allowed_values, disabled) and the resolved value in one object,
    without a second lookup against the schema.
    """

    value: str


class SettingsStore:
    """Data-access methods for project/application settings.

    Settings are defined once in ``settings_defaults.toml`` (key, scope, type,
    default, allowed_values, disabled). The database stores only *overrides* —
    a row exists only when a value differs from its schema default. Reading
    falls back to the schema default when no override row exists.

    Each accessor has a single, well-defined return type. Calling the wrong
    accessor for a setting's declared type raises :class:`SettingTypeMismatchError`
    rather than returning a value of unexpected type.

    Args:
        session: An active SQLAlchemy Session provided by the application's
            session factory (SessionManager) — typically injected via FastAPI
            dependency injection.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._overrides_cache: Optional[Dict[tuple, str]] = None
        self._overrides_cache_project_id: Optional[int] = None

    def _get_overrides_cache(self, project_id: Optional[int]) -> Dict[tuple, str]:
        if self._overrides_cache is None or self._overrides_cache_project_id != project_id:
            self._overrides_cache = self._load_overrides_map(project_id)
            self._overrides_cache_project_id = project_id
        return self._overrides_cache

    def _invalidate_cache(self) -> None:
        self._overrides_cache = None

    # ------------------------------------------------------------------
    # Typed reads
    # ------------------------------------------------------------------

    def get_str(self, setting_key: str, project_id: Optional[int] = None) -> str:
        """Return the effective value of a STRING or ENUM setting.

        Raises:
            KeyError: If *setting_key* is not in the schema.
            SettingTypeMismatchError: If the setting's declared type is not
                STRING or ENUM.
        """
        entry = self._require_entry(setting_key)
        self._require_type(entry, {SettingType.STRING, SettingType.ENUM})
        return self._resolve_raw(entry, project_id).value

    def get_int(self, setting_key: str, project_id: Optional[int] = None) -> int:
        """Return the effective value of an INTEGER setting.

        Raises:
            KeyError: If *setting_key* is not in the schema.
            SettingTypeMismatchError: If the setting's declared type is not INTEGER.
        """
        entry = self._require_entry(setting_key)
        self._require_type(entry, {SettingType.INTEGER})
        return int(self._resolve_raw(entry, project_id).value)

    def get_bool(self, setting_key: str, project_id: Optional[int] = None) -> bool:
        """Return the effective value of a BOOLEAN setting.

        Raises:
            KeyError: If *setting_key* is not in the schema.
            SettingTypeMismatchError: If the setting's declared type is not BOOLEAN.
        """
        entry = self._require_entry(setting_key)
        self._require_type(entry, {SettingType.BOOLEAN})
        return self._resolve_raw(entry, project_id).value.lower() in ("true", "1")

    def get_raw(self, setting_key: str, project_id: Optional[int] = None) -> ResolvedSetting:
        """Return the schema definition and effective value for *setting_key*, regardless of type.

        Useful for generic display/export code that doesn't care about the
        declared type but wants both the value and its metadata (type,
        scope, default, allowed_values, disabled) in one place. Prefer
        :meth:`get_str`/:meth:`get_int`/:meth:`get_bool` wherever the caller
        knows what type it expects and only needs the value.
        """
        entry = self._require_entry(setting_key)
        return self._resolve_raw(entry, project_id)

    def get_all_raw(
        self, project_id: Optional[int] = None, scope: Optional[str] = None
    ) -> Dict[str, ResolvedSetting]:
        """Return schema definitions and effective values for every setting in *scope*.

        Args:
            project_id: The project scope to resolve project-scoped settings
                against. Ignored for application-scoped settings.
            scope: Restrict to ``"application"`` or ``"project"`` settings.
                If ``None``, returns both.

        Returns:
            A dict mapping setting_key to a :class:`ResolvedSetting` (schema
            metadata plus resolved value). Every setting defined in the
            schema (matching *scope*) is present, whether or not it has an
            override row.
        """
        schema = self._load_settings_schema()
        overrides = self._load_overrides_map(project_id)
        result: Dict[str, ResolvedSetting] = {}

        # Per setting resolution is performed lazily
        for key, entry in schema.items():
            if scope is not None and entry.scope != scope:
                continue
            scoped_project_id = project_id if entry.scope == "project" else None
            value = overrides.get((key, scoped_project_id), entry.default)
            result[key] = ResolvedSetting(**entry.model_dump(), value=value)
        return result

    def get_definition(self, setting_key: str) -> SettingDef:
        """Return the schema definition for *setting_key* (type, scope, default, etc.)."""
        return self._require_entry(setting_key)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def update(self, setting_key: str, setting_value: str, project_id: Optional[int] = None) -> None:
        """Set an override value for *setting_key*, validated against the schema.

        Creates the override row if it doesn't exist yet, or updates it if
        it does. Takes and stores the raw string form — callers use the
        typed getters to read it back with a well-defined type.

        Args:
            setting_key: The key that identifies the setting.
            setting_value: The new raw string value to store.
            project_id: The project scope, ignored for application-scoped
                settings.

        Raises:
            KeyError: If *setting_key* is not present in the schema.
            ValueError: If *setting_value* fails type or enum validation.
            SettingDisabledError: If the setting is marked ``disabled``.
        """
        entry = self._require_entry(setting_key)
        if entry.disabled:
            raise SettingDisabledError(f"Setting {setting_key!r} is read-only")
        self._validate_setting(setting_key, setting_value, entry)

        scoped_project_id = project_id if entry.scope == "project" else None
        override = self._session.scalar(
            select(SettingOverride)
            .where(SettingOverride.setting_key == setting_key)
            .where(SettingOverride.project_id == scoped_project_id)
        )
        if override is not None:
            override.value = setting_value
        else:
            self._session.add(SettingOverride(
                setting_key=setting_key,
                project_id=scoped_project_id,
                value=setting_value,
            ))
        self._invalidate_cache()

    def reset(self, setting_key: str, project_id: Optional[int] = None) -> None:
        """Delete the override for *setting_key*, reverting it to the schema default.

        A no-op if no override row exists. Disabled settings never have
        override rows (enforced in :meth:`update`), so this is always safe
        to call regardless of ``disabled``.

        Raises:
            KeyError: If *setting_key* is not present in the schema.
        """
        entry = self._require_entry(setting_key)
        scoped_project_id = project_id if entry.scope == "project" else None
        override = self._session.scalar(
            select(SettingOverride)
            .where(SettingOverride.setting_key == setting_key)
            .where(SettingOverride.project_id == scoped_project_id)
        )
        if override is not None:
            self._session.delete(override)
        self._invalidate_cache()

    def reset_all(self, project_id: Optional[int] = None, scope: Optional[str] = None) -> None:
        """Delete all overrides for the given scope, reverting everything to defaults.
        ...
        """
        schema = self._load_settings_schema()
        keys = {k for k, e in schema.items() if scope is None or e.scope == scope}
        self._session.execute(
            delete(SettingOverride).where(
                SettingOverride.setting_key.in_(keys),
                (SettingOverride.project_id == project_id) | (SettingOverride.project_id.is_(None)),
            )
        )
        self._invalidate_cache()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_raw(self, entry: SettingDef, project_id: Optional[int]) -> ResolvedSetting:
        scoped_project_id = project_id if entry.scope == "project" else None
        overrides = self._get_overrides_cache(project_id)
        value = overrides.get((entry.key, scoped_project_id), entry.default)
        return ResolvedSetting(**entry.model_dump(), value=value)

    def _load_overrides_map(self, project_id: Optional[int]) -> Dict[tuple, str]:
        rows = self._session.scalars(
            select(SettingOverride).where(
                (SettingOverride.project_id == project_id) | (SettingOverride.project_id.is_(None))
            )
        ).all()
        return {(row.setting_key, row.project_id): row.value for row in rows}

    @staticmethod
    def _require_entry(key: str) -> SettingDef:
        schema = SettingsStore._load_settings_schema()
        if key not in schema:
            raise KeyError(f"Unknown setting: {key!r}")
        return schema[key]

    @staticmethod
    def _require_type(entry: SettingDef, allowed: set[SettingType]) -> None:
        if entry.type not in allowed:
            raise SettingTypeMismatchError(
                f"Setting {entry.key!r} has type {entry.type.value!r}; "
                f"expected one of {[t.value for t in allowed]}"
            )

    @staticmethod
    def _validate_setting(key: str, value: str, entry: SettingDef) -> None:
        match entry.type:
            case SettingType.INTEGER:
                try:
                    int(value)
                except ValueError:
                    raise ValueError(f"Setting {key!r} expects an integer value, got {value!r}")
            case SettingType.BOOLEAN:
                if value.lower() not in ("true", "false", "1", "0"):
                    raise ValueError(f"Setting {key!r} expects a boolean value, got {value!r}")
            case SettingType.ENUM:
                allowed = entry.allowed_values or []
                if value not in allowed:
                    raise ValueError(f"Setting {key!r} must be one of {allowed}, got {value!r}")
            case SettingType.STRING:
                pass  # accepts any value

    @staticmethod
    @lru_cache(maxsize=1)
    def _load_settings_schema() -> Dict[str, SettingDef]:
        with _SETTINGS_DEFAULTS_PATH.open("rb") as fh:
            data = tomllib.load(fh)
        return {key: SettingDef(key=key, **meta) for key, meta in data["settings"].items()}