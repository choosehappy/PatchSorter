FROM postgis/postgis:16

# Install build dependencies
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    cmake \
    postgresql-server-dev-16 \
    libh3-dev \
    ca-certificates \
    postgresql-16-h3 \
    && rm -rf /var/lib/apt/lists/*