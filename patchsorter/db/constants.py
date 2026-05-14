import os

CITUS_HEAD_HOST = os.environ.get("CITUS_HEAD_HOST", "localhost")
CITUS_HEAD_PORT = int(os.environ.get("CITUS_HEAD_PORT", "5432"))
CITUS_HEAD_DB = os.environ.get("CITUS_HEAD_DB", "postgres")
CITUS_HEAD_USER = os.environ.get("CITUS_HEAD_USER", "postgres")
CITUS_HEAD_PASSWORD = os.environ.get("CITUS_HEAD_PASSWORD", "password")
