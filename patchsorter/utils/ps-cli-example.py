# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:light
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.4.1
#   kernelspec:
#     display_name: Python 3
#     language: python
#     name: python3
# ---

import requests
import json
import argparse
from  datetime import datetime
import time
import cv2
import numpy as np
import matplotlib.pyplot as plt
import os


# +
headers = {'Content-Type': 'application/json'}

parser = argparse.ArgumentParser(description='create projects and link images')
parser.add_argument('-s', '--server', help="host with port, default http://127.0.0.1:5555 ", default="http://127.0.0.1:5555", type=str)
parser.add_argument('-p', '--projname', help="project to create/add to", required=True, type=str)
parser.add_argument('-d', '--directory', help="", type=str)
parser.add_argument('-i', '--description', help="", type=str)
parser.add_argument('-n', '--nclasses', help="", required=True, type=int)


#args = parser.parse_args()
#args = parser.parse_args(["-nnuclei",r"C:\temp\qa_testsets\nuclei\*.png"])
#args = parser.parse_args(["-ntubules",r"C:\temp\qa_testsets\tubules\*.png"])
args = parser.parse_args([r"-p1D1","-n2",r"-dD:\research\chuv_alex_mel\masks\1D1",'-imydescription'])


base_url=args.server
projname=args.projname
directory = args.directory
nclasses=args.nclasses
description=args.description


# +
## ----- Create Project and get Projid

filters = [dict(name='name', op='==', val=projname)]
params = dict(q=json.dumps(dict(filters=filters)))

final_url=f"{base_url}/api/db/project"
print(final_url)

response = requests.get(final_url, params=params, headers=headers)
response = response.json()

if(not response['num_results']):
    print(f"Project '{projname}' doesn't exist, creating...",end="")
    
    data = {'name': projname,'date': datetime.now().isoformat(), 'no_of_label_type': nclasses,
           'description': description}
    response = requests.post(final_url, json=data)
    
    if(response.status_code==201):
        print("done!")
        response = response.json()
        projid=response['id']

    else:
        print(response.text)
                        
else:
    print(f"Project '{projname}' exists....")
    projid=response['objects'][0]['id']


# +
#---- upload directory
#http://localhost:5555/api/mytest/image_folder?file_path=D:\research\chuv_alex_mel\masks\1C1
#file_path: D:\research\chuv_alex_mel\masks\1C1
        
        
final_url=f"{base_url}/api/{projname}/image_folder"
print(final_url)

data = {'file_path': directory}
response = requests.post(final_url, params=data)


    
if(response.status_code==201):
    print("done!")
    response = response.json()
    print(response)



# +
#--- make patches
        
        
final_url=f"{base_url}/api/{projname}/make_patches"
print(final_url)


response = requests.get(final_url)

make_patches_jobid=response.json()['job']['id']

status=None
while status!='DONE':
    filters = [dict(name='id', op='eq', val=make_patches_jobid)]
    params = dict(q=json.dumps(dict(filters=filters)))
    time.sleep(5)
    final_url = f'{base_url}/api/db/job'
    response = requests.get(final_url, params=params, headers=headers)
    response=response.json()
    status=response['objects'][0]['status']
    print(f"make_patches status: {status}")

# +
#--- embed patches
        
final_url=f"{base_url}/api/{projname}/embed"
print(final_url)

response = requests.get(final_url)

make_embed_jobid=response.json()['job']['id']


status=None
while status!='DONE':
    time.sleep(5)
    filters = [dict(name='id', op='eq', val=make_embed_jobid)]
    params = dict(q=json.dumps(dict(filters=filters)))

    final_url = f'{base_url}/api/db/job'
    response = requests.get(final_url, params=params, headers=headers)
    response=response.json()
    status=response['objects'][0]['status']
    print(f"make_patches status: {status}")

# +
## ---- Upload image example 
img_fname = r"D:\research\chuv_alex_mel\masks\1J1_-_2019-09-10_16.37.42_0_25288_16568.png"
image = cv2.cvtColor(cv2.imread(img_fname), cv2.COLOR_BGR2RGB)
img_fname_base=os.path.basename(img_fname)

files = {'file': open(img_fname, 'rb')}
final_url=f"{base_url}/api/{projname}/image"

print(final_url)
print(f"Uploading file '{img_fname}'...",end="")


response = requests.post(final_url, files=files)
if(response.status_code==201):
    print("done!") 

print(response.text)

# +
## ---- Upload mask example -- This won't work until #677 #708 are resolved
img_fname = r"D:\research\chuv_alex_mel\masks\1J1_-_2019-09-10_16.37.42_0_25288_16568_mask.png"
image = cv2.cvtColor(cv2.imread(img_fname), cv2.COLOR_BGR2RGB)
img_fname_base=os.path.basename(img_fname)

files = {'file': open(img_fname, 'rb')}
final_url=f"{base_url}/api/{projname}/image/1J1_-_2019-09-10_16.37.42_0_25288_16568.png/mask"

print(final_url)
print(f"Uploading file '{img_fname}'...",end="")


response = requests.post(final_url, files=files)
if(response.status_code==201):
    print("done!") 

print(response.text)

# +
#--- get prediction image example
final_url = f'{base_url}/api/{projname}/image/1D1_-_2019-09-10_16.17.22_0_26160_26160.png/pred'
response = requests.get(final_url)

#--- wait until job is done---
response = requests.get(final_url)
img =cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
plt.imshow(img)
