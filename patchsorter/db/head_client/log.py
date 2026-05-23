from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session


class LogStore:
    """Data-access methods for the ``log`` table.

    The log table records application-level events and is not associated with
    any specific project.

    Args:
        session: An active SQLAlchemy Session provided by the application's
            session factory (SessionManager) — typically injected via FastAPI
            dependency injection.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self,
        name: str,
        message: str,
        level: str = "INFO",
    ) -> None:
        """Append a single log entry.

        The timestamp is set to the database server's ``NOW()``.

        Args:
            name: The source or component name that generated this log entry
                (e.g. ``"patchsorter.api.v1"``).
            message: Human-readable log message.
            level: Severity level string.  Common values are ``"DEBUG"``,
                ``"INFO"``, ``"WARNING"``, and ``"ERROR"``.  Defaults to
                ``"INFO"``.
        """
        self._session.execute(
            text(
                """
                INSERT INTO log (name, timestamp, level, message)
                VALUES (:name, NOW(), :level, :message)
                """
            ),
            {"name": name, "level": level, "message": message},
        )

    def query(
        self,
        level: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return recent log entries, optionally filtered by severity level.

        Results are ordered by ``timestamp`` descending (most recent first).

        Args:
            level: If provided, only rows whose ``level`` matches this value
                exactly are returned.  Pass ``None`` to return entries at all
                severity levels.
            limit: Maximum number of rows to return.  Defaults to ``100``.

        Returns:
            A list of dicts, one per log entry.
        """
        if level is not None:
            rows = self._session.execute(
                text(
                    """
                    SELECT * FROM log
                    WHERE level = :level
                    ORDER BY timestamp DESC
                    LIMIT :limit
                    """
                ),
                {"level": level, "limit": limit},
            ).mappings().all()
        else:
            rows = self._session.execute(
                text(
                    """
                    SELECT * FROM log
                    ORDER BY timestamp DESC
                    LIMIT :limit
                    """
                ),
                {"limit": limit},
            ).mappings().all()
        return [dict(r) for r in rows]
