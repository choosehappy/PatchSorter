FROM rayproject/ray:2.49.2-py312-cu126
SHELL ["/bin/bash", "-c"]

USER root

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" --no-install-recommends \
        build-essential \
        cmake \
        ca-certificates \
        libglib2.0-0 \
        libjpeg-dev \
        libpng-dev \
        gcc gfortran libopenblas-dev liblapack-dev cython3 \
        libtk8.6 \
        procps \
        libopenslide0 \
        curl \
        ffmpeg \
        libsm6 \
        libxext6 \
        memcached \
        libgdal-dev \
        gdal-bin \
        python3-gdal \
        tmux \
        # development tools
        git \
        vim

RUN curl -LSfs https://raw.githubusercontent.com/cantino/mcfly/master/ci/install.sh | sh -s -- --git cantino/mcfly && \
    echo 'eval "$(mcfly init bash)"' >> ~/.bashrc && touch /home/ray/.bash_history

# Install node and npm
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
RUN apt-get install -y nodejs && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

RUN chown ray:users /opt
USER ray
RUN mkdir -p /opt/PatchSorter
WORKDIR /opt/PatchSorter

COPY --chown=ray:users ../pyproject.toml /opt/PatchSorter/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install torch torchvision --system \
        --index-url https://download.pytorch.org/whl/cu126 && \
    uv pip install -r pyproject.toml --system
    
COPY --chown=ray:users ./ /opt/PatchSorter/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install . --system

COPY --chown=ray:users ../patchsorter/client/package.json ../patchsorter/client/package-lock.json /opt/
ENV NODE_PATH=/opt/node_modules
WORKDIR /opt
RUN npm ci

WORKDIR /opt/PatchSorter

ENV PYTHONPYCACHEPREFIX=/opt/ps_pycache