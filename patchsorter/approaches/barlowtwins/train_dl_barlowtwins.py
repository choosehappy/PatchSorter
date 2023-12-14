import matplotlib.pyplot as plt
import argparse
import json
import math
import os
import sys
import time
import traceback
from collections import Counter

import cv2
import numpy as np
import tables
import torch
from albumentations import *
from albumentations.pytorch import ToTensor

from torch import nn
from torch.utils.data import DataLoader
from torchsummary import summary
from torch.utils.tensorboard import SummaryWriter


from model.barlowtwins import Barlowtwins


# +

class Dataset(object):
    def __init__(self, fname, unlabeled_percent=-1, img_transform=None, mask_image=False):
        self.fname = fname
        self.mask_image = mask_image
        self.img_transform = img_transform
        self.unlabeled_percent = unlabeled_percent
        with tables.open_file(self.fname, 'r') as db:
            self.labledidx = (db.root.ground_truth_label[:] != -1).nonzero()[0]  # get indexes of labeled eamples
            self.nlabledidx = len(self.labledidx)

            if self.unlabeled_percent == -1 or self.nlabledidx == 0:
                self.nitems = db.root.patch.shape[0]
            else:
                # get indexes of unlabeled eamples
                self.unlabledidx = (db.root.ground_truth_label[:] == -1).nonzero()[0]

                nunlabeled = int(
                    self.nlabledidx * unlabeled_percent)  # compute how many unlabled shoud be added based on parameter

                self.nitems = min(nunlabeled + self.nlabledidx, db.root.patch.shape[0])
                print(f"using total items: {self.nitems}\t\tlabeled: {self.nlabledidx}\t\tunlabeled: {nunlabeled}")

        self.imgs = None

    def __getitem__(self, index):
        # opening should be done in __init__ but seems to be
        # an issue with multithreading so doing here. need to do it everytime, otherwise hdf5 crashes

        with tables.open_file(self.fname, 'r') as db:
            if self.unlabeled_percent != -1 and self.nlabledidx > 0:
                # --- need to modify index
                if index < self.nlabledidx:
                    index = self.labledidx[index]  # specifically pull out a labeled example
                else:
                    index = np.random.choice(self.unlabledidx)  # otherwise pull a random unlabeled example

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
            img_new_v1 = self.img_transform(image=img)['image']
            img_new_v2 = self.img_transform(image=img)['image']

        return img_new_v1, img_new_v2, img, pred, gt, mask

    def __len__(self):
        return self.nitems


# +
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Train UNet')
    parser.add_argument('project_name', type=str)
    parser.add_argument('pytable_name', type=str)
    parser.add_argument('nclasses', type=int)

    parser.add_argument('-c', '--codesize', help="vector for embedding, default 32", default=32, type=int)
    parser.add_argument('-p', '--patchsize', help="patchsize, default 32", default=32, type=int)
    parser.add_argument('-n', '--numepochs', help="", default=100, type=int)
    parser.add_argument('--numepochsinital', help="", default=100, type=int)
    parser.add_argument('-s', '--numearlystopepochs',
                        help="Number of epochs to stop early if no validation progress has been made", default=-1,
                        type=int)
    parser.add_argument('-l', '--numminepochs',
                        help="Minimum number of epochs required before early stopping, default 300", default=300,
                        type=int)
    parser.add_argument('--minlossearlystop',
                        help="losses below this value will temrinate training, default=.01", default=.01,
                        type=float)
    parser.add_argument('-b', '--batchsize', help="", default=16, type=int)
    parser.add_argument('-m', '--prev_model_init', help="", default=None, type=str)
    parser.add_argument('-r', '--numworkers',
                        help="number of data loader workers to use", default=0,
                        type=int)
    parser.add_argument('-i', '--gpuid', help="GPU ID, set to -2 to use CPU", default=0, type=int)
    parser.add_argument('-o', '--outdir', help="", default="./", type=str)
    parser.add_argument('--maskpatches', action="store_true", help="use mask to mask patches")
    parser.add_argument('-t', '--temperature', help="", default=0.07, type=float)
    parser.add_argument('-u', '--unlabeled_percent', help="", default=2, type=float)

    args = parser.parse_args()

#    args = parser.parse_args(
#        ['chuv_mel', r"C:\temp\PatchSorter_v2\projects\p\patches_p.pytable", '2', '-p32', '-n50',
#         '-s-1', '-l10', '-b128', '-c128', '-o./projects/p/models/0/',
#         '-r-1'])

    print(f"args: {args}")


    # +

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


    try:
        print(f'USER: Starting Training DL model', flush=True)

        # ----- parse command line arguments
        device = torch.device(args.gpuid if args.gpuid != -2 and torch.cuda.is_available() else 'cpu')
        model = Barlowtwins(codesize=args.codesize, nclasses=args.nclasses).to(device)
        #summary(model, (3, 32, 32))

        #---
        if args.prev_model_init:
            print(f'USER: Using previous model as initial point: {args.prev_model_init}', flush=True)
            # load checkpoint to CPU and then put to device https://discuss.pytorch.org/t/saving-and-loading-torch-models-on-2-machines-with-different-number-of-gpu-devices/6666
            checkpoint = torch.load(args.prev_model_init, map_location=lambda storage, loc: storage)
            model.load_state_dict(checkpoint["model_dict"])

        #---


        patch_size = args.patchsize
        batch_size = args.batchsize

        numworkers = args.numworkers if args.numworkers != -1  else os.cpu_count()

        num_epochs = args.numepochs if args.prev_model_init else args.numepochsinital
        num_epochs_earlystop = args.numearlystopepochs if args.numearlystopepochs > 0 else float("inf")
        num_min_epochs = args.numminepochs

        projname = args.project_name

        pytable = args.pytable_name

        newmodeldir = args.outdir
        iteration = newmodeldir.split("/")[4]
        os.makedirs(newmodeldir, exist_ok=True)

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

        data_train = Dataset(pytable, unlabeled_percent=args.unlabeled_percent,
                             img_transform=img_transform, mask_image=args.maskpatches)  # img_transform)
        data_train_loader = DataLoader(data_train, batch_size=batch_size, shuffle=True,
                                       num_workers=numworkers, pin_memory=True)  # ,pin_memory=True)

        (img_new_v1, img_new_v2, img, pred, gt, mask)=data_train[9]
        # fig, ax = plt.subplots(1,3, figsize=(10,4))  # 1 row, 2 columns
        # print(pred)
        # ax[0].imshow(np.moveaxis(img_new_v1.numpy(),0,-1))
        # ax[1].imshow(np.moveaxis(img_new_v2.numpy(), 0, -1))
        # ax[2].imshow(img)
        # plt.show()


        optim = torch.optim.Adam(model.parameters(), weight_decay=.001)

        start_time = time.time()

        writer = SummaryWriter()
        criterion = nn.MSELoss()
        l1loss = nn.L1Loss

        with tables.open_file(args.pytable_name, 'r') as db:
            cw = Counter(db.root.ground_truth_label[:])

        class_weight = np.asarray([cw.get(k, 0) for k in range(args.nclasses)])
        if class_weight.sum():  # some labling has occured so modify weights
            class_weight = torch.from_numpy(1 - class_weight / class_weight.sum()).type('torch.FloatTensor').to(device)
        else:
            class_weight = None

        criterion_pred = nn.CrossEntropyLoss(ignore_index=-1, weight=class_weight)

        best_loss = np.Infinity
        best_epoch = -1

        for epoch in range(num_epochs):

            if (epoch > num_min_epochs and epoch - best_epoch > num_epochs_earlystop):
                print(
                    f'USER: DL model training stopping due to lack of progress. Current Epoch:{epoch} Last Improvement: {best_epoch}',
                    flush=True)
                break

            if (best_loss < args.minlossearlystop):
                print(
                    f'USER: DL model training stopping a loss value of {best_loss} being below the loss value of minlossearlystop {args.minlossearlystop}',
                    flush=True)
                break

            all_loss = torch.zeros(0).to(device)

            # for X, img_old,pred,gt,mask in tqdm(data_train_loader):

            for X1, X2, img_old, pred, gt1, mask in data_train_loader:
                X1 = X1.to(device)
                X2 = X2.to(device)

                z1 = model.features(X1)
                z2 = model.features(X2)

                barlow_loss = model.loss(z1, z2)/10

                gt1 = gt1.type(torch.LongTensor).to(device)

                pred_class1 = model.forward_pred(z1)
                pred_class2 = model.forward_pred(z2)


                class_loss1 = 100 * criterion_pred(pred_class1, gt1)  # --- convert into weight from config file
                class_loss2 = 100 * criterion_pred(pred_class2, gt1)  # --- convert into weight from config file

                loss = barlow_loss + class_loss1 + class_loss2

                optim.zero_grad()
                loss.backward()
                optim.step()

            all_loss = loss
            all_loss = all_loss.detach().cpu().numpy().mean()
            writer.add_scalar(f'train/loss', all_loss, epoch)

            print(
                f'PROGRESS: {epoch + 1}/{num_epochs} | {timeSince(start_time, (epoch + 1) / num_epochs)} | {loss.data}',
                flush=True)
            print('%s ([%d/%d] %d%%), loss: %.4f ' % (timeSince(start_time, (epoch + 1) / num_epochs),
                                                      epoch + 1, num_epochs, (epoch + 1) / num_epochs * 100, all_loss),
                  end="", flush=True)

            # should update here to only safe if best epoch, no need to have all of them

            if all_loss < best_loss:
                best_loss = all_loss
                best_epoch = epoch

                print("  **")
                state = {'epoch': epoch + 1,
                         'model_dict': model.state_dict(),
                         'optim_dict': optim.state_dict()}

                torch.save(state,
                           f"{newmodeldir}/best_model_barlowtwins_C{args.codesize}_N{args.nclasses}_P{args.patchsize}.pth")

        print(f'USER: Done Training of DL model', flush=True)

        print(f"RETVAL: {json.dumps({'project_name': projname, 'iteration': iteration})}", flush=True)
    except:
        track = traceback.format_exc()
        track = track.replace("\n", "\t")
        print(f"ERROR: {track}", flush=True)
        sys.exit(1)
