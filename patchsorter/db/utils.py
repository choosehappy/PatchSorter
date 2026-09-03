"""Utilities for DB access: SessionManager and DatabaseManager.

These were previously defined in the package root but have been moved
here to keep the package `__init__` small.
"""
from contextlib import contextmanager
from typing import Any, Generator, List

import pandas as pd
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

_SHARD_MAP_SQL = """
    SELECT shard_a, shard_b
    FROM (
        SELECT s1.shardid AS shard_a,
               s2.shardid AS shard_b,
               ROW_NUMBER() OVER (ORDER BY s1.shardid) AS rn
        FROM pg_dist_shard s1
        JOIN pg_dist_shard s2
          ON s1.shardminvalue = s2.shardminvalue
         AND s1.shardmaxvalue = s2.shardmaxvalue
        JOIN pg_dist_partition p1
          ON s1.logicalrelid = p1.logicalrelid
        JOIN pg_dist_partition p2
          ON s2.logicalrelid = p2.logicalrelid
        JOIN pg_dist_placement pl1
          ON s1.shardid = pl1.shardid
        JOIN pg_dist_placement pl2
          ON s2.shardid = pl2.shardid
        WHERE s1.logicalrelid = :table_a::regclass
          AND s2.logicalrelid = :table_b::regclass
          AND p1.colocationid = p2.colocationid
          AND pl1.groupid = :groupid
          AND pl2.groupid = :groupid
    ) shard_map
"""


_WORKER_FILTER = "WHERE rn % :num_workers = :current_worker_rank"


def build_local_node_shard_map_query(
    table_a: str,
    table_b: str,
    groupid: int,
) -> text:
    return text(_SHARD_MAP_SQL).bindparams(
        table_a=table_a,
        table_b=table_b,
        groupid=groupid,
    )


def build_local_worker_shard_map_query(
    table_a: str,
    table_b: str,
    num_workers: int,
    current_worker_rank: int,
    groupid: int,
) -> text:
    query = text(f"{_SHARD_MAP_SQL.rstrip()}\n{_WORKER_FILTER}")
    return query.bindparams(
        table_a=table_a,
        table_b=table_b,
        num_workers=num_workers,
        current_worker_rank=current_worker_rank,
        groupid=groupid,
    )



class CitusShardMap:
    def __init__(self, rows: List[Any]):
        self.map = pd.DataFrame(
            [(r.shard_a, r.shard_b) for r in rows],
            columns=["shard_a", "shard_b"],
        )

    @staticmethod
    def from_rows(rows: List[Any]) -> "CitusShardMap":
        return CitusShardMap(rows)

    def get_table_a_shard_list(self) -> List[int]:
        return self.map["shard_a"].tolist()

    def get_table_b_shard_list(self) -> List[int]:
        return self.map["shard_b"].tolist()

    def get_b_shard_for_a_shard(self, shard_a: int) -> int:
        row = self.map[self.map["shard_a"] == shard_a]
        if row.empty:
            raise KeyError(f"shard_a={shard_a} not found in shard map")
        return int(row.iloc[0]["shard_b"])

    def get_a_shard_for_b_shard(self, shard_b: int) -> int:
        row = self.map[self.map["shard_b"] == shard_b]
        if row.empty:
            raise KeyError(f"shard_b={shard_b} not found in shard map")
        return int(row.iloc[0]["shard_a"])

