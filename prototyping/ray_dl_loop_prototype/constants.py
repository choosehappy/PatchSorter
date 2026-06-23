# constants.py
# Centralized configuration for Citus/Postgres connections (matches docker-compose)

# Single-node Citus/Postgres (matches docker-compose)
CITUS_HEAD_HOST = "localhost"
CITUS_HEAD_PORT = 5432
CITUS_HEAD_DB = "postgres"
CITUS_HEAD_USER = "postgres"
CITUS_HEAD_PASSWORD = "password"
