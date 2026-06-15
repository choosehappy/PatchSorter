import os

CITUS_HEAD_HOST = os.environ.get("CITUS_HEAD_HOST", "localhost")
CITUS_HEAD_PORT = int(os.environ.get("CITUS_HEAD_PORT", "5439"))
CITUS_HEAD_DB = os.environ.get("CITUS_HEAD_DB", "postgres")
CITUS_HEAD_USER = os.environ.get("CITUS_HEAD_USER", "postgres")
CITUS_HEAD_PASSWORD = os.environ.get("CITUS_HEAD_PASSWORD", "password")

CITUS_WORKER_HOST = os.environ.get("CITUS_WORKER_HOST", "localhost")
CITUS_WORKER_PORT = int(os.environ.get("CITUS_WORKER_PORT", "5439"))
CITUS_WORKER_DB = os.environ.get("CITUS_WORKER_DB", "postgres")
CITUS_WORKER_USER = os.environ.get("CITUS_WORKER_USER", "postgres")
CITUS_WORKER_PASSWORD = os.environ.get("CITUS_WORKER_PASSWORD", "password")
