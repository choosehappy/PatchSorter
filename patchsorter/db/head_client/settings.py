from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


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
        project_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Insert or update a setting and return the resulting row.

        If a row with the same (*setting_key*, *project_id*) combination
        already exists and is not disabled, its ``setting_value`` is updated
        in-place.  If the existing row has ``disabled = TRUE`` the value is
        not changed.

        Args:
            setting_key: The key that identifies the setting.
            setting_value: The new value for the setting.
            project_id: The project this setting belongs to, or ``None`` for
                an application-level setting.

        Returns:
            A dict with all columns of the upserted row.
        """
        row = self._session.execute(
            text(
                """
                INSERT INTO settings (project_id, setting_key, setting_value)
                VALUES (:project_id, :key, :value)
                ON CONFLICT (setting_key, project_id)
                DO UPDATE SET setting_value = EXCLUDED.setting_value
                    WHERE NOT settings.disabled
                RETURNING *
                """
            ),
            {"project_id": project_id, "key": setting_key, "value": setting_value},
        ).mappings().one()
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
