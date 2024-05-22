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

import argparse
import json
import os
import sys
import traceback
import cv2
import glob
import dill

import numpy as np
import tables
# +
import torch
from albumentations import *
from albumentations.pytorch import ToTensor
from scipy.spatial.distance import cdist

if __name__ == '__main__':
    try:
        # # +
        parser = argparse.ArgumentParser(description='Search by image in the embedding space')
        parser.add_argument('-p', '--patchsize', help="Patchsize, default 32", default=32, type=int)
        parser.add_argument('-i', '--gpuid', help="GPU ID, set to -2 to use CPU", default=0, type=int)
        parser.add_argument('-n', '--nneighbors', help="How many matches to be returned?", default=1000, type=int)
        parser.add_argument('-m', '--maxthresh', help="maximum value for positive result", default=np.Inf,
                            type=float)
        parser.add_argument('project_name', type=str)
        parser.add_argument('pytable', help="pytable to search ")
        parser.add_argument('input_image_fname', help="input image filename to do searching with")
        parser.add_argument('model_dir', help="directory containing model starting with 'best'...")

        args = parser.parse_known_args()[0]

        print(f"args: {args}")

        patch_size = args.patchsize

        nneighbors = args.nneighbors
        maxthresh = args.maxthresh if args.maxthresh > -1 else float("inf")

        model_dir = args.model_dir
        model_name = os.path.basename(glob.glob(f"{model_dir}/best*.pth")[0])
        model_fullpath = os.path.join(model_dir, model_name)
        model_type = model_name.split("_")[2]
        codesize = int(model_name.split("_")[3].replace("C", ""))
        nclasses = int(model_name.split("_")[4].replace("N", ""))

        device = torch.device(args.gpuid if args.gpuid != -2 and torch.cuda.is_available() else 'cpu')
        # device = torch.device('cpu')

        # ---
        sys.path.append(f'./approaches/{model_type}')
        model_class = getattr(__import__(f"model.{model_type}"), model_type)
        model_class = getattr(model_class, model_type.capitalize())

        model = model_class(codesize=codesize, nclasses=nclasses).to(device)

        if (os.path.exists(model_fullpath)):
            checkpoint = torch.load(model_fullpath, map_location=lambda storage,
                                                                        loc: storage)  # load checkpoint to CPU and then put to device https://discuss.pytorch.org/t/saving-and-loading-torch-models-on-2-machines-with-different-number-of-gpu-devices/6666
            model.load_state_dict(checkpoint["model_dict"])
        # ---
        # summary(model, (3, args.patchsize, args.patchsize))

        img_transform = Compose([
            CenterCrop(patch_size, patch_size),
            ToTensor()
        ])

        model.eval()
        io = cv2.cvtColor(cv2.imread(args.input_image_fname), cv2.COLOR_BGR2RGB)
        io = cv2.resize(io, (patch_size, patch_size))
        io = img_transform(image=io)["image"].to(device)[None, ::]

        Xvecs = model.features(io)
        vec_query = Xvecs.detach().cpu().numpy()

        with tables.open_file(args.pytable, 'a') as db:
            vecs_all = db.root.feats[:]

        if vec_query.shape[1] != vecs_all.shape[1]:
            print(f'USER: Feature vector length doesnt match expected size, assuming needing to apply dimredux',
                  flush=True)
            pca_reducer = dill.load(open(f"{model_dir}/pca_reducer.pkl", "rb"))
            vec_query = pca_reducer.transform(vec_query)
        else:
            print(f'USER: Done computing query feature vector, doing search', flush=True)

        print(f'USER: Done getting feature vectors. Searching', flush=True)

        no_of_objs = vecs_all.shape[0]
        ind = []
        hits = []
        hits_dist = []
        if nneighbors >= no_of_objs:
            nneighbors = no_of_objs-1
            print(f"User: Nneighbors larger than no of objects in project changed it to {nneighbors}",
                  flush=True)
        dists = cdist(vec_query, vecs_all, metric='euclidean').squeeze()
        ind = np.argpartition(dists, nneighbors)[0:nneighbors]
        if len(ind):
            hits = ind[np.argsort(dists[ind])]  # return these two values
            if len(hits):
                hits_dist = dists[hits]

                # filter by maxthresh
            hits = hits[hits_dist < maxthresh]
            hits_dist = hits_dist[hits_dist < maxthresh]


            # convert to list for json
            hits = [int(h) for h in hits]
            hits_dist = list(hits_dist)
            # retval = [(int(i), d) for i, d in zip(idx, idx_dist)] #--- front end needs individual hits so will send seperately

        print(f"RETVAL: {json.dumps({'project_name': args.project_name, 'hits': hits, 'idx_dist': hits_dist})}",
              flush=True)

    except:
        track = traceback.format_exc()
        track = track.replace("\n", "\t")
        print(f"ERROR: {track}", flush=True)
        sys.exit(1)
