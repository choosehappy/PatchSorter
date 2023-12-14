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

import json
import traceback
import argparse
import sys
import os

import numpy as np
import tables
# +
import torch
import umap
from albumentations import *
from albumentations.pytorch import ToTensor
from collections import Counter

from sklearn.cluster import KMeans
from torch import nn
from torch.utils.data import DataLoader
from torchsummary import summary
from tqdm.autonotebook import tqdm
import dill as pickle

from model.barlowtwins import Barlowtwins
from sklearn.decomposition import PCA


# +
class Dataset(object):
    def __init__(self, fname, img_transform=None, mask_image=False):
        self.fname = fname
        self.mask_image = mask_image
        self.img_transform = img_transform
        with tables.open_file(self.fname, 'r') as db:
            self.nitems = db.root.patch.shape[0]

        self.imgs = None

    def __getitem__(self, index):
        # opening should be done in __init__ but seems to be
        # an issue with multithreading so doing here. need to do it everytime, otherwise hdf5 crashes

        with tables.open_file(self.fname, 'r') as db:

            # get the requested image and mask from the pytable
            img = db.root.patch[index, :, :, :]
            mask = db.root.mask[index, :, :]
            pred = db.root.prediction[index]
            gt = db.root.ground_truth_label[index]

        mask = mask == mask[mask.shape[0] // 2, mask.shape[1] // 2]  # likely isnt' still needed, but is here incase
        if (self.mask_image):
            img = np.multiply(img, mask[:, :, None])

        img_new = img
        if self.img_transform:
            img_new = self.img_transform(image=img)['image']

        return img_new, img, pred, gt, mask

    def __len__(self):
        return self.nitems


if __name__ == '__main__':
    try:
        # # +
        parser = argparse.ArgumentParser(description='Put patches into pytable for PatchSorter')
        parser.add_argument('-c', '--codesize', help="vector for embedding, default 32", default=32, type=int)
        parser.add_argument('-d', '--dimredux',
                            help="reduce dimensions to this value via PCA before embedding to improve performanc, default -1 (disabled)",
                            default=-1, type=int)
        parser.add_argument('-p', '--patchsize', help="Patchsize, default 32", default=32, type=int)
        parser.add_argument('-b', '--batchsize', help="", default=512, type=int)
        parser.add_argument('-i', '--gpuid', help="GPU ID, set to -2 to use CPU", default=0, type=int)
        parser.add_argument('-s', '--semisupervised', action="store_true", help="use umap in a semi supervised mode")
        parser.add_argument('--maskpatches', action="store_true", help="use mask to mask patches")
        parser.add_argument('--save_features', action="store_true", help="write features to DB for later use")
        parser.add_argument('-r', '--numworkers',
                            help="number of data loader workers to use, NOTE: will be set to 0 for windows", default=0,
                            type=int)
        parser.add_argument('project_name', type=str)
        parser.add_argument('-o', '--outdir', help="", default="./", type=str)
        parser.add_argument('pytable', help="pytable to modify the embed_x and embed_y of ")
        parser.add_argument('nclasses', type=int)

        args = parser.parse_args()
        # args = parser.parse_args([ 'p', '-o./projects/p/models/0',
        # './projects/p/patches_p.pytable', '-b1024', '-p32', '-r-1', '-c128', '2', '--maskpatches'])

        print(f"args: {args}")

        # if os.name == "nt":
        #     numworkers = 0
        # else:
        # Changes made after the SimCLR Support added
        numworkers = args.numworkers if args.numworkers != -1 else os.cpu_count()
        # numworkers = os.cpu_count()

        patch_size = args.patchsize
        batch_size = args.batchsize

        modelid = args.outdir.split("/")[4]

        model_name = f"{args.outdir}/best_model_barlowtwins_C{args.codesize}_N{args.nclasses}_P{args.patchsize}.pth"

        device = torch.device(args.gpuid if args.gpuid != -2 and torch.cuda.is_available() else 'cpu')

        model = Barlowtwins(codesize=args.codesize, nclasses=args.nclasses).to(device)

        os.makedirs(args.outdir, exist_ok=True)
        
        if (os.path.exists(model_name)):
            checkpoint = torch.load(model_name, map_location=lambda storage,
                                                                    loc: storage)  # load checkpoint to CPU and then put to device https://discuss.pytorch.org/t/saving-and-loading-torch-models-on-2-machines-with-different-number-of-gpu-devices/6666
            model.load_state_dict(checkpoint["model_dict"])
        else: #this model is randomly made, so will need to save weights for other usage
            
            
            state = {'epoch': -1,
                     'model_dict': model.state_dict(),
                     'optim_dict': None}

            torch.save(state,model_name)
                       

        # summary(model, (3, args.patchsize, args.patchsize))

        img_transform = Compose([
            CenterCrop(patch_size, patch_size),
            ToTensor()
        ])

        data_train = Dataset(args.pytable, img_transform=img_transform, mask_image=args.maskpatches)  # img_transform)
        data_train_loader = DataLoader(data_train, batch_size=batch_size,
                                       shuffle=False, num_workers=numworkers, pin_memory=True)  # ,pin_memory=True)

        all_vecs_full = []
        all_preds_full = []
        model.eval()
        # for X, img_old, pred, gt, mask in tqdm(data_train_loader):
        for batchi, (X, img_old, pred, gt, mask) in enumerate(data_train_loader):
            print(f'PROGRESS: {batchi} / {len(data_train_loader)}', flush=True)
            X = X.to(device)
            Xvecs = model.features(X)
            preds = model.forward_pred(Xvecs)
            # Xvecs = F.normalize(Xvecs, dim=1)

            vecs = Xvecs.detach().cpu().numpy()
            all_vecs_full.extend(vecs)
            all_preds_full.extend(preds.detach().cpu().numpy())

            # preds = np.zeros((vecs.shape[0], args.nclasses))
            # all_preds_full.extend(preds)

        all_preds_full = np.vstack(all_preds_full)
        all_vecs_full = np.vstack(all_vecs_full)
        print(f"USER: Starting first PCA reduction", flush=True)
        if args.dimredux > 0:
            pca = PCA(n_components=args.dimredux)
            all_vecs_full = pca.fit_transform(all_vecs_full)
            pickle.dump(pca, open(f"{args.outdir}/pca_reducer.pkl", 'wb'))
        print(f"USER: Finished  PCA reduction", flush=True)

        print(f'USER: Done getting feature vectors. Starting to Embed', flush=True)
        reducer = umap.UMAP()  # n_neighbors=50,min_dist=0.0)

        if args.semisupervised:
            with tables.open_file(args.pytable, 'r') as db:
                label = db.root.ground_truth_label[:]
            embedding = reducer.fit_transform(all_vecs_full, y=label)
        else:
            embedding = reducer.fit_transform(all_vecs_full)

        pickle.dump(reducer, open(f"{args.outdir}/umap_model.pkl", 'wb'))
        print(f'USER: Done embedding', flush=True)

        with tables.open_file(args.pytable, 'a') as db:
            db.root.embed_x[:] = embedding[:, 0]
            db.root.embed_y[:] = embedding[:, 1]

            if args.save_features:
                if not hasattr(db.root, 'feats'):
                    dim = args.dimredux if args.dimredux > 0 else args.codesize
                    db.create_earray(db.root, "feats", tables.Float16Atom(), shape=np.append([0], dim),
                                     chunkshape=np.append([1], dim),
                                     filters=tables.Filters(complevel=6, complib='zlib'))
                    db.root.feats.append(all_vecs_full)
                else:
                    db.root.feats[:]=all_vecs_full

            xmax = float(db.root.embed_x[:].max())
            xmin = float(db.root.embed_x[:].min())
            ymax = float(db.root.embed_y[:].max())
            ymin = float(db.root.embed_y[:].min())

            if np.all(db.root.prediction[:] == -1):
                kmeans = KMeans(n_clusters=args.nclasses).fit(embedding)
                preds = kmeans.labels_

            else:
                preds = np.argmax(all_preds_full, axis=1)
                db.root.pred_score[:] = np.max(all_preds_full, axis=1)

            print(f"USER: Class Counts: {Counter(preds)}", flush=True)

            db.root.prediction[:] = preds

        print(f"USER: Done updating embeddings!", flush=True)

        print(
            f"RETVAL: {json.dumps({'project_name': args.project_name, 'modelid': modelid, 'xmax': xmax, 'xmin': xmin, 'ymax': ymax, 'ymin': ymin})}",
            flush=True)

    except:
        track = traceback.format_exc()
        track = track.replace("\n", "\t")
        print(f"ERROR: {track}", flush=True)
        sys.exit(1)
