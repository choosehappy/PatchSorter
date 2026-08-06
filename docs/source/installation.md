# Installation
**General Prerequisites**

Ensure the following prerequisites are met on your machine:
- [Docker](https://docs.docker.com/get-docker/) Install Docker desktop for Windows, MacOS or Linux. For Linux, you can alternatively install [docker engine](https://docs.docker.com/engine/install/).
- [NVIDIA Driver](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/)
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

## 1. Quick Start
The following instructions detail how to install PatchSorter on a single node (e.g., a laptop with GPU support).

### 1.1. Installation Steps
1. Download the docker compose file from the PatchSorter repository:
    ```bash
    curl -O https://raw.githubusercontent.com/choosehappy/PatchSorter/v2.0/deployment/docker-compose.yaml
    ```

2. Run the docker compose file:
    ```bash
    docker compose -f docker-compose.yaml up -d
    ```

## 2. Multi-node Deployment (work in progress)
PatchSorter can be deployed to a multi-node cluster, with each cluster node possessing one or more GPUs. PatchSorter will allocate GPU workers to maximize training and prediction throughput.

## 3. For Developers
### 3.1. Additional Prerequisites
- VS Code with the devcontainers extension installed.

### 3.2. Installation Steps
1. Clone the git repository and checkout the v2.0 branch:
    ```bash
    git clone https://github.com/choosehappy/PatchSorter.git
    cd PatchSorter
    git checkout v2.0
    ```


2. *(Optional)* Configure the `deployment/.env` file to set the host ports that each PatchSorter service will be exposed on:

| Variable           | Default | Description |
| ------------------ | ------- | ----------- |
| CITUS_PORT         | 5438    | Host port   |
| SERVER_PORT        | 5008    | Host port   |
| UI_PORT            | 5178    | Host port   |
| RAY_DASHBOARD_PORT | 8268    | Host port   |


3. Within VS Code, open the cloned repository and click on the "Reopen in Container" button to build the devcontainer. This will create a docker container with all the necessary dependencies to run PatchSorter.
![image](https://github.com/user-attachments/assets/b776577f-a4c2-4eb8-858c-c603ac20cc6d)