FROM rayproject/ray:2.54.0.1ea498-py313-cpu
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
        sqlite3 \
        libsqlite3-dev \
        libsqlite3-mod-spatialite \
        libtk8.6 \
        procps \
        libopenslide0 \
        curl \
        ffmpeg \
        libsm6 \
        libxext6 \
        memcached \
        graphviz \
        libgraphviz-dev \
        libgdal-dev \
        gdal-bin \
        python3-gdal \
        tmux \
        # development tools
        git \
        vim

RUN curl -LSfs https://raw.githubusercontent.com/cantino/mcfly/master/ci/install.sh | sh -s -- --git cantino/mcfly && \
    echo 'eval "$(mcfly init bash)"' >> ~/.bashrc && touch /home/ray/.bash_history


# Set the working directory in the container

RUN chown ray:users /opt
USER ray
RUN mkdir -p /opt/QuickAnnotator
WORKDIR /opt/QuickAnnotator


WORKDIR /opt

COPY --chown=ray:users ./requirements.txt ./

RUN uv pip install -r /opt/requirements.txt --system

WORKDIR /opt/PatchSorter

USER ray
ENV PYTHONPYCACHEPREFIX=/opt/ps_pycache