import os

CITUS_HEAD_HOST = os.environ.get("CITUS_HEAD_HOST", "localhost")
CITUS_HEAD_PORT = int(os.environ.get("CITUS_HEAD_PORT", "5439"))
CITUS_HEAD_DB = os.environ.get("CITUS_HEAD_DB", "postgres")
CITUS_HEAD_USER = os.environ.get("CITUS_HEAD_USER", "postgres")
CITUS_HEAD_PASSWORD = os.environ.get("CITUS_HEAD_PASSWORD", "password")

CITUS_LOCAL_HOST = os.environ.get("CITUS_LOCAL_HOST", "localhost")
CITUS_LOCAL_PORT = int(os.environ.get("CITUS_LOCAL_PORT", "5439"))
CITUS_LOCAL_DB = os.environ.get("CITUS_LOCAL_DB", "postgres")
CITUS_LOCAL_USER = os.environ.get("CITUS_LOCAL_USER", "postgres")
CITUS_LOCAL_PASSWORD = os.environ.get("CITUS_LOCAL_PASSWORD", "password")
