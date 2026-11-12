"""Utilities for DB access: SessionManager and DatabaseManager.

These were previously defined in the package root but have been moved
here to keep the package `__init__` small.
"""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
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

    def dispose_engine(self) -> None:
        """Dispose of the engine's connection pool.

        Call this from a ``DataLoader`` worker's ``worker_init_fn`` after a
        ``spawn``-context fork so the worker drops any inherited connection
        pool state and lazily opens fresh connections on first use.
        """
        self.engine.dispose()

# This query finds every shard of *table_name* that is placed on a given
# Citus worker node (``groupid``). It does this by joining the table's
# ``pg_dist_shard`` rows against ``pg_dist_placement`` on ``shardid``,
# filtering to the target ``groupid``.
#
# Returns: shard_id — one row per local shard.
_LOCAL_SHARDS_SQL = """
    SELECT shard_id
    FROM (
        SELECT s.shardid AS shard_id,
               ROW_NUMBER() OVER (ORDER BY s.shardid) AS rn
        FROM pg_dist_shard s
        JOIN pg_dist_placement pl
          ON s.shardid = pl.shardid
        WHERE s.logicalrelid = CAST(:table_name AS regclass)
          AND pl.groupid = :groupid
    ) local_shards
"""

# An additional filter implements round-robin distribution of local shards (shards placed on a Citus worker node) to ray train workers.
_WORKER_FILTER = "WHERE rn % :num_workers = :current_worker_rank"


def build_local_node_shards_query(
    table_name: str,
    groupid: int,
) -> text:
    """Build a query returning every shard of *table_name* local to a node.

    Args:
        table_name: Name of the distributed table to inspect.
        groupid: Citus worker group ID to filter placements.

    Returns:
        A SQLAlchemy ``text`` object with bound parameters ready to execute.
    """
    return text(_LOCAL_SHARDS_SQL).bindparams(
        table_name=table_name,
        groupid=groupid,
    )


def build_local_worker_shards_query(
    table_name: str,
    num_workers: int,
    current_worker_rank: int,
    groupid: int,
) -> text:
    """Build a query returning the shards of *table_name* assigned to one ray train worker.

    Like ``build_local_node_shards_query`` but adds a modulo filter so that
    each ray train worker only sees its own subset of local shards.

    Args:
        table_name: Name of the distributed table to inspect.
        num_workers: Total number of ray train worker processes assigned to the local node.
        current_worker_rank: This ray train worker's rank (0-based index).
        groupid: Citus worker group ID to filter placements.

    Returns:
        A SQLAlchemy ``text`` object with bound parameters and the worker
        filter clause appended.
    """
    query = text(f"{_LOCAL_SHARDS_SQL.rstrip()}\n{_WORKER_FILTER}")
    return query.bindparams(
        table_name=table_name,
        num_workers=num_workers,
        current_worker_rank=current_worker_rank,
        groupid=groupid,
    )
