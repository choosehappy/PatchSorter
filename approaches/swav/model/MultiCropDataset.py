import tables
import numpy as np
from albumentations import *
from albumentations.pytorch import ToTensor
import cv2


def get_transform(size_crops, nmb_crops, min_scale_crops, max_scale_crops):
    trans = []
    for i in range(len(size_crops)):
        randomresizedcrop = RandomResizedCrop(height=size_crops[i], width=size_crops[i],
                                              scale=(min_scale_crops[i], max_scale_crops[i]))

        trans.extend([Compose([
            randomresizedcrop,
            VerticalFlip(p=.5),
            HorizontalFlip(p=.5),
            Blur(p=.5),
            GaussNoise(p=.5, var_limit=(10.0, 50.0)),
            ISONoise(p=.5, intensity=(0.1, 0.5), color_shift=(0.01, 0.05)),
            RandomBrightness(p=.5, limit=(-0.2, 0.2)),
            RandomContrast(p=.5, limit=(-0.2, 0.2)),
            RandomGamma(p=.5, gamma_limit=(80, 120), eps=1e-07),
            MultiplicativeNoise(p=.5, multiplier=(0.9, 1.1), per_channel=True, elementwise=True),
            HueSaturationValue(hue_shift_limit=20, sat_shift_limit=10, val_shift_limit=10, p=.9),
            Rotate(p=1, border_mode=cv2.BORDER_REFLECT),
            ToTensor()
        ])] * nmb_crops[i])
    return trans


# ------------


class Dataset(object):
    def __init__(self, fname, size_crops, nmb_crops, min_scale_crops, max_scale_crops, mask_image):
        assert len(size_crops) == len(nmb_crops)
        assert len(min_scale_crops) == len(nmb_crops)
        assert len(max_scale_crops) == len(nmb_crops)

        self.fname = fname
        self.mask_image = mask_image
        self.img_transform = get_transform(size_crops, nmb_crops, min_scale_crops, max_scale_crops)
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
        if self.mask_image:
            img = np.multiply(img, mask[:, :, None])

        multi_crops = img
        if self.img_transform:
            multi_crops = list(map(lambda trans: trans(image=img)['image'], self.img_transform))

        return multi_crops, img, pred, gt, mask

    def __len__(self):
        return self.nitems
