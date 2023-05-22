""" @Author Cedric Wakler
simple python script to create a nuclei data set based on WSI data for labeling with PatchSorter

requirements
openslide-python              1.1.2
numpy                         1.21.6
scipy                         1.7.3
scikit-image                  0.19.3
histocartography              0.2.1
opencv-python                 4.2.0.34

""""
import os
import glob

import staintools
import openslide
import cv2
import numpy as np
from tqdm import tqdm
from scipy.signal import fftconvolve
from skimage.measure import regionprops
from histocartography.preprocessing import NucleiExtractor


MASKPATH = './masks'
TILEPATH = './tiles'
REFERENCE_PATH='add path to stain normalisation reference png'
WSI_PATH = 'add path to your wsi data set'


stain_norm = False # True in manuscript
tiles_per_wsi = 20
ds = 16
wsi_level = 0  # assumes 40x scan
tile_size = 500

np.random.seed(6)

nuclei_detector = NucleiExtractor()
tissue_masks = glob.glob(f'{WSI_PATH}/*')

if stain_norm:
    target = cv2.cvtColor(cv2.imread(stain_reference), cv2.COLOR_BGR2RGB)
    normalizer = staintools.StainNormalizer(method='vahadane')
    normalizer.fit(target.copy())

def check_outof_bound(l, i, b):
    """ helper function to check the boarder conditions"""
    return (l.shape[0] - b) < i.centroid[0] or i.centroid[0] < b or (l.shape[1] - b) < i.centroid[1] or i.centroid[1]  < b

def remove_boarder(labels_, thresh):
    """ helper function to remove nuclei at the boarder"""
    to_remove = [i for i in regionprops(labels_) if check_outof_bound(labels_, i, thresh)]

    l_copy = labels_.copy()
    for i in to_remove:
        l_copy[l_copy == i.label] = 0
    return l_copy


for fname in tqdm(files):
    wsin = os.path.splitext(os.path.basename(fname))[0]
    wsiext = os.path.splitext(os.path.basename(fname))[1]
    slide = openslide.open_slide(f'{WSI_PATH}/{wsin}{wsiext}')

    # create a non-tissue mask of the slide
    mask_level = osh.get_best_level_for_downsample(ds+0.5) # for numerical precision
    ds = osh.level_downsamples[mask_level]
    img = osh.read_region((0, 0), mask_level, osh.level_dimensions[mask_level])
    imgg = cv2.cvtColor(np.asarray(img)[:, :, 0:3], cv2.COLOR_RGB2GRAY)
        
    th, _ = cv2.threshold(imgg, thresh=0, maxval=255, type=cv2.THRESH_OTSU)
    th = max(220, th)
    mask = np.logical_and(imgg > 0, imgg < th)        

    # erode mask to not sample background patches
    mask = fftconvolve(mask.astype(np.uint8), np.ones((tile_size//ds, tile_size//ds)), mode = 'same')
    mask = mask > ((tile_size//ds)**2) * 0.9

    r, c = mask.nonzero()

    idx = np.random.choice(*[range(len(r))],tiles_per_wsi)
    for j, i in enumerate(idx):
        y = (r[i]) * ds
        x = (c[i]) * ds
        save_path = f'{wsin}_{tissue_type}_{x}_{y}'
        tile = slide.read_region((x,y), wsi_level, (tile_size, tile_size))
        if stain_tools:
            tile = normalizer.transform(np.array(tile)[:,:,0:3])

        labels, _ = nuclei_detector.process(tile)
        # add in boundary checks
        if np.all(labels == 0):
            continue
        m = remove_boarder(labels, 16)  # remove boarder region to reduce nuclei mirroring from PS
        cv2.imwrite(f'{TILEPATH}/{save_path}.png', cv2.cvtColor(tile, cv2.COLOR_RGB2BGR)) 
        cv2.imwrite(f'{MASKPATH}/{save_path}_mask.png', m.astype(np.float32))
