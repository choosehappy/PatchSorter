"""Utilities for DB access: SessionManager and DatabaseManager.

These were previously defined in the package root but have been moved
here to keep the package `__init__` small.
"""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.engine import URL


class SessionManager:
    """Manages an SQLAlchemy engine and session factory.

    The constructor requires explicit connection parameters. Use the
    client-level convenience factories (``head_client.get_client()`` or
    ``worker_client.get_client()``) to obtain instances initialized with
    the repository constants.
    """

    def __init__(
        self,
        host: str,
        port: int,
        dbname: str,
        user: str,
        password: str,
        pool_size: int = 10,
    ) -> None:
        self.engine = create_engine(
            URL.create(
                drivername="postgresql+psycopg",
                username=user,
                password=password,
                host=host,
                port=port,
                database=dbname,
            ),
            pool_size=pool_size,
        )
        self.session_factory = sessionmaker(bind=self.engine)

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        session: Session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_connection(self):
        """Return a raw psycopg connection from the engine pool."""
        return self.engine.raw_connection()


