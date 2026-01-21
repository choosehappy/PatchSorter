# Start from official PostGIS image
FROM postgis/postgis:16-3.4

# Install dependencies for building H3
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    postgresql-server-dev-16 \
    cmake \
    gcc \
    make \
    postgresql-16-h3 \
    && rm -rf /var/lib/apt/lists/*

# Expose default PostgreSQL port
EXPOSE 5432

# Set default user, password, and database via environment variables
ENV POSTGRES_USER=testuser
ENV POSTGRES_PASSWORD=mypassword
ENV POSTGRES_DB=testdb