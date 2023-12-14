import argparse
import json
import math
import os
import sys
import time
import scipy
from collections import Counter
from tqdm.autonotebook import tqdm
import ttach as tta



import cv2
import numpy as np
import tables
import torch
from albumentations import *
from albumentations.pytorch import ToTensor
# from tensorboardX import SummaryWriter
from torch.utils.tensorboard import SummaryWriter
from torch import nn
from torch.utils.data import DataLoader
from torchsummary import summary
from torchvision.models import DenseNet

# +

parser = argparse.ArgumentParser(description='Apply Densenet')
parser.add_argument('pytable_name', type=str)
parser.add_argument('nclasses', type=int)

parser.add_argument('-c', '--codesize', help="vector for embedding, default 32", default=32, type=int)
parser.add_argument('-p', '--patchsize', help="patchsize, default 32", default=32, type=int)
parser.add_argument('-m', '--model', help="",type=str)
parser.add_argument('-b', '--batchsize', help="", default=16, type=int)
parser.add_argument('-r', '--numworkers',
                    help="number of data loader workers to use, NOTE: will be set to 0 for windows", default=0,
                    type=int)
parser.add_argument('-i', '--gpuid', help="GPU ID, set to -2 to use CPU", default=0, type=int)
parser.add_argument('-o', '--outdir', help="", default="./", type=str)
parser.add_argument('--maskpatches', action="store_true", help="use mask to mask patches")

#args = parser.parse_args()
args = parser.parse_args([ r"/home/ajanowcz/PatchSorter/projects/1N1/patches_1N1.pytable","--maskpatches",
                          '2', '-p32', '-b32', '-m/home/ajanowcz/PatchSorter/projects/1V2/models/supervised/best_model_densenet_2_32_.pth', '-r-1'])

print(f"args: {args}")


# -


def asMinutes(s):
    m = math.floor(s / 60)
    s -= m * 60
    return '%dm %ds' % (m, s)


def timeSince(since, percent):
    now = time.time()
    s = now - since
    es = s / (percent + .00001)
    rs = es - s
    return '%s (- %s)' % (asMinutes(s), asMinutes(rs))


device = torch.device(args.gpuid if args.gpuid != -2 and torch.cuda.is_available() else 'cpu')

# +
growth_rate=32 
block_config=(2, 2, 2)
num_init_features=32
bn_size=2
drop_rate=0

model = DenseNet(growth_rate=growth_rate, block_config=block_config,
                 num_init_features=num_init_features, 
                 bn_size=bn_size, 
                 drop_rate=drop_rate, 
                 num_classes=args.nclasses).to(device)

checkpoint = torch.load(args.model)
model.load_state_dict(checkpoint["model_dict"])
tta_model = tta.ClassificationTTAWrapper(model, tta.aliases.d4_transform(), merge_mode='mean')
#summary(model, (3, 32, 32))
# -

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

        mask = mask == mask[mask.shape[0] // 2, mask.shape[1] // 2]
        if (self.mask_image):
            img = np.multiply(img, mask[:, :, None])

        img_new = img
        if self.img_transform:
            img_new = self.img_transform(image=img)['image']

        return img_new, img, pred, gt, mask

    def __len__(self):
        return self.nitems


# +
print(f'USER: Starting Training DL model', flush=True)


patch_size = args.patchsize
batch_size = args.batchsize

if os.name == "nt":
    numworkers = 0
else:
    numworkers = args.numworkers if args.numworkers != -1 else os.cpu_count()

pytablefname = args.pytable_name

# +
img_transform = Compose([
    ToTensor()
])

data_train = Dataset(pytablefname, img_transform=img_transform, mask_image=args.maskpatches)  # img_transform)
data_train_loader = DataLoader(data_train, batch_size=batch_size, shuffle=False,
                               num_workers=numworkers, pin_memory=True)  # ,pin_memory=True)
# -

import matplotlib.pyplot as plt
(img, img_old,pred,gt,mask)=data_train[9]
fig, ax = plt.subplots(1,3, figsize=(10,4))  # 1 row, 2 columns
print(pred)
ax[0].imshow(np.moveaxis(img.numpy(),0,-1))
ax[1].imshow(img_old)
ax[2].imshow(mask)

# +

all_preds_full = []

for batchi,(X, img_old, pred, gt, mask) in tqdm(enumerate(data_train_loader)):
    X = X.to(device)
    prediction = tta_model(X)  
    all_preds_full.extend(prediction.detach().cpu().numpy())

all_preds_full = np.vstack(all_preds_full)
# -

preds = np.argmax(all_preds_full,axis=1)
Counter(preds)

with tables.open_file(pytablefname, mode='a') as pytable:
    #pytable.root.ground_truth_label[:]=preds
    #pytable.root.ground_truth_label[:]=-1
    pytable.root.prediction[:]=preds

# +
#---for debug view of random subset
# nchoices=5
# with tables.open_file(pytablefname, mode='a') as pytable:

#     for ci in range(args.nclasses):
#         print(f"-----------{ci}--------")
#         idxs=np.random.choice(np.argwhere(preds==ci).flatten(),nchoices)
#         for idx in idxs:
#             plt.imshow(pytable.root.patch[idx,:,:,:].squeeze())
#             plt.show()
# -


