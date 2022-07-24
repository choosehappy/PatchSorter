FROM nvidia/cuda:11.0.3-cudnn8-devel-ubuntu20.04
CMD nvidia-smi
ENV PYTHONPATH "${PYTHONPATH}:/opt"

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" --no-install-recommends \
         build-essential \
         cmake \
         ca-certificates \
         libglib2.0-0 \
         libjpeg-dev \
         libpng-dev \
         python3.8 \
         python3.8-dev \
         python3-pip \
         python3-wheel \
         python3-setuptools \
         gcc gfortran libopenblas-dev liblapack-dev cython \
         sqlite3 \
         libsqlite3-dev

COPY ./cuda_11/requirements.txt /opt/PatchSorter/requirements.txt
WORKDIR /opt/PatchSorter
RUN pip3 install -U pip
RUN pip3 install -r requirements.txt
COPY . /opt/PatchSorter

ADD . /opt/PatchSorter
CMD ["python3", "PS.py"]
