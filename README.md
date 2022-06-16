# PatchSorter
---
PatchSorter is an open-source digital pathology tool for histologic object labeling.
![PS user interface screenshot](https://github.com/choosehappy/PatchSorter/wiki/images/patchsorter_tool.gif)

# Requirements
---
Tested with Python 3.8 and Chrome

Requires:
1. Python 
2. pip

And the following additional python package:
1. Flask_SQLAlchemy
2. scikit_image
3. scikit_learn
4. opencv_python_headless
5. scipy
6. requests
7. SQLAlchemy
8. torch
9. torchvision
10.Flask_Restless
11. numpy
12. Flask
13. umap_learn
14. Pillow
15. tensorboardX
16. ttach
17. albumentations
18. config
19. dill
20. Shapely
21. tables
22. tqdm

You can likely install the python requirements using something like (note python 3+ requirement):
```
pip3 install -r requirements.txt
```

The library versions have been pegged to the current validated ones. 
Later versions are likely to work but may not allow for cross-site/version reproducibility

We received some feedback that users could installed *torch*. Here, we provide a detailed guide to install
*Torch*
### Torch's Installation
The general guides for installing Pytorch can be summarized as following:
1. Check your NVIDIA GPU Compute Capability @ *https://developer.nvidia.com/cuda-gpus* 
2. Download CUDA Toolkit @ *https://developer.nvidia.com/cuda-downloads* 
3. Install PyTorch command can be found @ *https://pytorch.org/get-started/locally/* 

### Run
```
 E:\<<folder_path>>\PatchSorter>python PS.py
```
By default, it will start up on localhost:5555

*Warning*: virtualenv will not work with paths that have spaces in them, so make sure the entire path to `env/` is free of spaces.
### Config Sections
There are many modular functions in QA whose behaviors could be adjusted by hyper-parameters. These hyper-parameters can 
be set in the *config.ini* file

- [common]
- [flask]
- [sqlalchemy]
- [pooling]
- [make_patches]
- [frontend]
- [train_tl]
- [embed]

### Naming Conventions
- image name eg : train_1.png
- mask image name eg : train_1_mask.png
- csv file name eg: train_1.csv 


### Docker requirements
Docker is a set of platform as a service products that use OS-level virtualization to deliver software in packages called containers. Containers are isolated from one another and bundle their own software, libraries and configuration files.

In order to use Docker version of QA, user needs:
1. Nvidia driver supporting cuda. See documentation, [here](https://docs.nvidia.com/deploy/cuda-compatibility/index.html).
2. Docker Engine. See documentation, [here](https://docs.docker.com/engine/install/)
3. Nvidia-docker https://github.com/NVIDIA/nvidia-docker


Depending on your cuda version, we provide Dockerfiles for *cuda_10* and *cuda_11*.

To start the server, run either:
`docker build -t patchsorter -f cuda_10/Dockerfile .` 
or 
`docker build -t patchsorter -f cuda_11/Dockerfile .`
from the *PatchSorter* folder.

When the docker image is done building, it can be run by typing:

`docker run --gpus all -v /data/$CaseID/PatchSorter:/opt/PatchSorter -v /data/$CaseID/<location_of_images>/:/opt/imagedata -p 5555:5555 --shm-size=8G patchsorter`

In the above command, `-v /data/$CaseID/PatchSorter:/opt/PatchSorter` mounts the PS on host file system to the PS inside the container.
`/data/$CaseID/PatchSorter` should be the PS path on your host file system, `/opt/PatchSorter` is the PS path inside the container, which is specified in the *Dockerfile*.
If image files will be uploaded using the upload folder option image directory needs to be mounted as well.
`/data/$CaseID/<location_of_images>/` would be the path for images on your host file system, `/opt/imagedata` will be the path for the images inside the container.

*Note:* This command will forward port 5555 from the computer to port 5555 of the container, 
where our flask server is running as specified in the [config.ini]. The port number should match the config of running PS on host file system.

# Usage Documentation
---
See 
[wiki](https://github.com/choosehappy/PatchSorter/wiki)  
[User Manual](https://github.com/choosehappy/PatchSorter/wiki/User-Manual)  
[FAQ](https://github.com/choosehappy/PatchSorter/wiki/Frequently-Asked-Questions)

# Citation
---

Please use below to cite this paper if you find this repository useful or if you use the software shared here in your research.
```
 Talawalla T., Toth R., Walker C., Horlings H., Rea K., Rottenberg S., Madabhushi A., Janowczyk A., "PatchSorter a high throughput open-source digital pathology tool for histologic object labeling", European Society of Digital and Integrative Pathology (ESDIP), Germany, 2022
```
