import argparse
import json
import math
import os
import sys
import time
import scipy
from collections import Counter
from tqdm.autonotebook import tqdm


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
# from torchsummary import summary
from torchinfo import summary
from torchvision.models import DenseNet

# +

parser = argparse.ArgumentParser(description='Train Densenet')
parser.add_argument('pytable_name', type=str)
parser.add_argument('nclasses', type=int)

parser.add_argument('-c', '--codesize', help="vector for embedding, default 32", default=32, type=int)
parser.add_argument('-p', '--patchsize', help="patchsize, default 32", default=32, type=int)
parser.add_argument('-n', '--numepochs', help="", default=100, type=int)
parser.add_argument('-s', '--numearlystopepochs',
                    help="Number of epochs to stop early if no validation progress has been made", default=-1,
                    type=int)
parser.add_argument('-l', '--numminepochs',
                    help="Minimum number of epochs required before early stopping, default 300", default=300,
                    type=int)
parser.add_argument('-b', '--batchsize', help="", default=16, type=int)
parser.add_argument('-r', '--numworkers',
                    help="number of data loader workers to use, NOTE: will be set to 0 for windows", default=0,
                    type=int)
parser.add_argument('-i', '--gpuid', help="GPU ID, set to -2 to use CPU", default=0, type=int)
parser.add_argument('-o', '--outdir', help="", default="./", type=str)
parser.add_argument('--maskpatches', action="store_true", help="use mask to mask patches")

#args = parser.parse_args()
args = parser.parse_args([ r"C:\temp\PatchSorter\projects\chuv_mel_1U1\patches_chuv_mel_1U1.pytable", 
                          '2', '-p32', '-n50', '-s-1', '-l10', '-b32', '-o./projects/chuv_mel_1U1/models/final/', '-r0'])

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
# summary(model, (3, 32, 32))
summary(model, (args.batchsize, 3, 32, 32))

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


num_epochs = args.numepochs
num_epochs_earlystop = args.numearlystopepochs if args.numearlystopepochs > 0 else float("inf")
num_min_epochs = args.numminepochs

pytable = args.pytable_name
# -

newmodeldir = args.outdir
iteration = newmodeldir.split("/")[4]
os.makedirs(newmodeldir, exist_ok=True)

# +
img_transform = Compose([
    RandomScale(scale_limit=0.1, p=.9),
    PadIfNeeded(min_height=patch_size, min_width=patch_size),
    VerticalFlip(p=.5),
    HorizontalFlip(p=.5),
    Blur(p=.5),
    Downscale(p=.25, scale_min=0.64, scale_max=0.99),
    GaussNoise(p=.5, var_limit=(10.0, 50.0)),
    GridDistortion(p=.5, num_steps=5, distort_limit=(-0.3, 0.3),
                   border_mode=cv2.BORDER_REFLECT),
    ISONoise(p=.5, intensity=(0.1, 0.5), color_shift=(0.01, 0.05)),
    RandomBrightness(p=.5, limit=(-0.2, 0.2)),
    RandomContrast(p=.5, limit=(-0.2, 0.2)),
    RandomGamma(p=.5, gamma_limit=(80, 120), eps=1e-07),
    MultiplicativeNoise(p=.5, multiplier=(0.9, 1.1), per_channel=True, elementwise=True),
    HueSaturationValue(hue_shift_limit=20, sat_shift_limit=10, val_shift_limit=10, p=.9),
    Rotate(p=1, border_mode=cv2.BORDER_REFLECT),
    RandomCrop(patch_size, patch_size),
    ToTensor()
])

data_train = Dataset(pytable, img_transform=img_transform, mask_image=args.maskpatches)  # img_transform)
data_train_loader = DataLoader(data_train, batch_size=batch_size, shuffle=True,
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
optim = torch.optim.Adam(model.parameters(), weight_decay=.001)
start_time = time.time()
writer = SummaryWriter()


with tables.open_file(args.pytable_name, 'r') as db:
    cw=Counter(db.root.ground_truth_label[:])

class_weight=np.asarray([cw.get(k,0) for k in range(args.nclasses)])    
class_weight = torch.from_numpy(1-class_weight/class_weight.sum()).type('torch.FloatTensor').to(device)

criterion = nn.CrossEntropyLoss(ignore_index=-1, weight=class_weight)

best_loss = np.Infinity
best_epoch = -1



# +
for epoch in range(num_epochs):

    cmatrix = np.zeros((args.nclasses,args.nclasses))
    if (epoch > num_min_epochs and epoch - best_epoch > num_epochs_earlystop):
        print(
            f'USER: DL model training stopping due to lack of progress. Current Epoch:{epoch} Last Improvement: {best_epoch}',
            flush=True)
        break

    all_loss = torch.zeros(0).to(device)

    # for X, img_old,pred,gt,mask in tqdm(data_train_loader):
    for X, img_old, pred, gt, mask in tqdm(data_train_loader):
        X = X.to(device)  # [N, 3, H, W]
        gtgpu = gt.type('torch.LongTensor').to(device)
        
        prediction = model(X)  
        loss = criterion(prediction, gtgpu)
        
        all_loss = torch.cat((all_loss, loss.detach().view(1, -1)))

        #        print(f"{loss}\t{lossl1}\t{lossmse}")
        
        p=prediction.detach().cpu().numpy()
        cpredflat=np.argmax(p,axis=1).flatten()
        yflat=gt.numpy().flatten()

        

        
        cmatrix+= scipy.sparse.coo_matrix((np.ones(yflat[yflat!=-1].shape[0], dtype=np.int64), (yflat[yflat!=-1], cpredflat[yflat!=-1])),
                            shape=(args.nclasses, args.nclasses), dtype=np.int64).toarray()

        optim.zero_grad()
        loss.backward()
        optim.step()
    all_acc=(cmatrix/cmatrix.sum()).trace()
    all_loss = all_loss.cpu().numpy().mean()
    writer.add_scalar(f'train/loss', all_loss, epoch)
    #
    #print(f'PROGRESS: {epoch + 1}/{num_epochs} | {timeSince(start_time, (epoch + 1) / num_epochs)} | {loss.data} | {all_acc}',
    #      flush=True)
    print('%s ([%d/%d] %d%%), loss: %.4f  all_acc %.4f' % (timeSince(start_time, (epoch + 1) / num_epochs),
                                              epoch + 1, num_epochs, (epoch + 1) / num_epochs * 100, all_loss,all_acc),flush=True)

    print(f"{cmatrix}",end="")
    # should update here to only safe if best epoch, no need to have all of them

    if all_loss < best_loss:
        best_loss = all_loss
        best_epoch = epoch

        print("  **")
        state = {'epoch': epoch + 1,
                 'model_dict': model.state_dict(),
                 'optim_dict': optim.state_dict()}

        torch.save(state, f"{newmodeldir}/best_model_densenet_{args.nclasses}_{args.patchsize}_.pth")
    else:
        print("")
        

