# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:light
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.11.0
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
import numpy as np
import skimage.measure
import tables
from PS_scikitlearn import extract_patches
from PatchSorter.PS_db import MaskTypeEnum
import csv


def find_nearest_non_black_pixel(img, target):
    nonzero = np.argwhere(img>0)
    distances = np.sqrt((nonzero[:,0] - target[0]) ** 2 + (nonzero[:,1] - target[1]) ** 2)
    try:
        nearest_index = np.argmin(distances)
        return nonzero[nearest_index]
    except ValueError:
        return None

def _read_grayscale_mask(image_mask_path):
    #Setting the flag to 0, to load as grayscale, seems to default to 8 bit.
    #Setting the flag to -1 loads the image as is.https://localcoder.org/opencv-reading-a-16-bit-grayscale-image
    image_grayscale_mask = cv2.imread(image_mask_path, -1)
    image_grayscale_mask = _add_padding_img(image_grayscale_mask)
    return image_grayscale_mask

def _read_rgb_mask(image_mask_path):
    # Supports QA RGB , Binary Mask.
    # Supports Labelled RGB and GrayScale Mask.
    image_rgb_mask = cv2.cvtColor(cv2.imread(image_mask_path), cv2.COLOR_BGR2RGB)
    image_rgb_mask = image_rgb_mask[:, :, 1].squeeze()
    image_rgb_mask = _add_padding_img(image_rgb_mask)
    return image_rgb_mask

def _add_padding_img(unpadded_mask):
    img_mask_padded = np.pad(unpadded_mask, [(patchsize, patchsize), (patchsize, patchsize)],
                               mode="constant",constant_values=0)
    return img_mask_padded

def _makepatch_quick_annotator_mask(mask_path,csv_path):
    image_mask = _read_rgb_mask(mask_path)
    if csv_path:
        rows, cols, ground_truth_labels = _process_csvlabels(csv_path)
    else:
        rps = _obtain_regionprops(image_mask)
        rows, cols = _obtain_object_coord(rps)
        ground_truth_labels = _generate_default_gtlabels(rows)
    return image_mask, rows, cols, ground_truth_labels

def _makepatch_labeled_mask(mask_path,csv_path):
    image_mask = _read_rgb_mask(mask_path)
    if csv_path:
        rows, cols, ground_truth_labels = _process_csvlabels(csv_path)
    else:
        rps = _obtain_regionprops(image_mask) ## Temp using this to be sure if it solves the issue.
        rows, cols, gtvals = _obtain_object_coord_with_gt(rps)
        uniques = np.unique(image_mask)
        non_black_uniques = uniques[uniques != 0].tolist()

        lbl_rows = []
        lbl_cols = []
        ground_truth_labels = []
        for i, (row, col,gt) in enumerate(zip(rows, cols,gtvals)):
            lbl_rows.append(int(row))
            lbl_cols.append(int(col))
            gt_label = non_black_uniques.index(gt)
            ground_truth_labels.append(gt_label)

        rows = np.asarray(lbl_rows) #not adding patchsize as these rows were picked from an already padded image mask.
        cols = np.asarray(lbl_cols) #not adding patchsize as these rows were picked from an already padded image mask.
        ground_truth_labels = np.asarray(ground_truth_labels)
        print(np.unique(ground_truth_labels))
    return image_mask, rows, cols, ground_truth_labels

def _makepatch_binary_mask(mask_path,csv_path):
    image_mask = _read_grayscale_mask(mask_path)
    if csv_path:
        rows, cols, ground_truth_labels = _process_csvlabels(csv_path)
    else:
        rps = _obtain_regionprops(image_mask)
        rows, cols = _obtain_object_coord(rps)
        ground_truth_labels = _generate_default_gtlabels(rows)
    return image_mask, rows, cols, ground_truth_labels

def _makepatch_index_mask(mask_path,csv_path):
    image_mask = _read_grayscale_mask(mask_path)
    if csv_path:
        rows, cols, ground_truth_labels = _process_csvlabels(csv_path)
    else:
        rps = _obtain_regionprops(image_mask)
        rows, cols = _obtain_object_coord(rps)
        ground_truth_labels = _generate_default_gtlabels(rows)
    return image_mask, rows, cols, ground_truth_labels

def _obtain_regionprops(mask):
    img_vals = skimage.measure.label(mask)
    rps = skimage.measure.regionprops(img_vals,mask)
    return rps

## Obtains row col values based of centroids
def _obtain_object_coord(rps):
    rowscols = np.round(np.asarray([rp.centroid for rp in rps]))
    rows, cols = rowscols[:, 0], rowscols[:, 1]
    return rows , cols
## Obtains row col and gt values based on intensity.
def _obtain_object_coord_with_gt(rps):
    rows = []
    cols = []
    ground_truth_vals = []
    for i, (rp) in enumerate(rps):
        ground_truth_val = rp.intensity_image[rp.intensity_image.nonzero()][0]
        row,col = rp.centroid
        rows.append(int(row))
        cols.append(int(col))

        ground_truth_vals.append(ground_truth_val)
    return rows, cols,ground_truth_vals


def _generate_default_gtlabels(rows):
    gt_labels = np.ones_like(rows) * -1
    return gt_labels

def _process_csvlabels(csv_file_path):
    rows = []
    cols = []
    ground_truth_labels = []

    for csvline in open(csv_file_path):
        scsvline = csvline.strip().split(",")
        rows.append(int(float(scsvline[0])))
        cols.append(int(float(scsvline[1])))

        ground_truth_labels.append(int(scsvline[2]) if len(scsvline) == 3 else -1)

    rows = np.asarray(rows) + patchsize #adding patchsize to compensate for the padding placed on the image, the coordinates are shifting
    cols = np.asarray(cols) + patchsize #adding patchsize to compensate for the padding placed on the image, the coordinates are shifting
    ground_truth_labels = np.asarray(ground_truth_labels)
    return rows, cols, ground_truth_labels

# +
try:
    # # +
    parser = argparse.ArgumentParser(description='Put patches into pytable for PatchSorter')
    parser.add_argument('project_name', type=str)
    parser.add_argument('-p', '--patchsize', help="Patchsize, default 32", default=32, type=int)
    parser.add_argument('csvfile',
                        help="CSV file of files to import of format: imageid,image_path,image_mask_path,image_csv_path")
    parser.add_argument('pytableoutput', help="pytable to either append or create")
    parser.add_argument('str_delimiter',help="delimeter defined in config.ini")

    #args = parser.parse_args(["project_name","input.csv", "pytableout.pytable"])
    args = parser.parse_args()
    project_name = args.project_name
    patchsize = args.patchsize

    # +
    storage = {}  # holder for future pytables
    if not os.path.exists(args.pytableoutput):  # DB doesn't exist
        hdf5_file = tables.open_file(args.pytableoutput, mode='w')
        patch_shape = np.array((patchsize, patchsize, 3))
        mask_shape = np.array((patchsize, patchsize))
        #filters = tables.Filters(complevel=6,complib='zlib')  # we can also specify filters, such as compression, to improve storage speed
        #Modifying the compression and removed the chunkshape from all feilds except patch and mask
        #This changes will improve the query performance.
        filters = tables.Filters(complevel=9, complib='blosc')

        hdf5_file.create_earray(hdf5_file.root, "imgID", tables.UInt16Atom(), shape=[0],filters=filters)
        hdf5_file.create_earray(hdf5_file.root, "patch_row", tables.UInt16Atom(), shape=[0],filters=filters)
        hdf5_file.create_earray(hdf5_file.root, "patch_column", tables.UInt16Atom(), shape=[0],filters=filters)

        hdf5_file.create_earray(hdf5_file.root, "prediction", tables.Int8Atom(), shape=[0],filters=filters)
        hdf5_file.create_earray(hdf5_file.root, "ground_truth_label", tables.Int8Atom(), shape=[0],filters=filters)

        hdf5_file.create_earray(hdf5_file.root, "pred_score", tables.Float16Atom(), shape=[0],filters=filters)

        hdf5_file.create_earray(hdf5_file.root, "embed_x", tables.Float16Atom(), shape=[0],filters=filters)
        hdf5_file.create_earray(hdf5_file.root, "embed_y", tables.Float16Atom(), shape=[0],filters=filters)

        hdf5_file.create_earray(hdf5_file.root, "patch", tables.UInt8Atom(), shape=np.append([0], patch_shape),
                                chunkshape=np.append([1], patch_shape), filters=filters)
        hdf5_file.create_earray(hdf5_file.root, "mask", tables.UInt8Atom(), shape=np.append([0], mask_shape),
                                chunkshape=np.append([1], mask_shape), filters=filters)

    else:
        hdf5_file = tables.open_file(args.pytableoutput, mode='a')

    # +
    fnames = []
    # sep_str = config.get('image_details', 'delimitby', fallback=',')
    error_patch = {}
    for line in open(args.csvfile, 'r'):
        sline = line.strip().split(args.str_delimiter)
        mask_type = sline[0]
        imageid = sline[1]
        image_path = sline[2]
        img_mask_path =sline[3]
        img_csv_path = sline[4]
        fnames.append(image_path)
        print(f"USER: Working on image {image_path}!", flush=True)

        img = cv2.cvtColor(cv2.imread(image_path), cv2.COLOR_BGR2RGB)
        imgshape_orig = img.shape
        img = np.pad(img, [(patchsize, patchsize), (patchsize, patchsize), (0, 0)], mode="reflect")  # compensate for edge issues
        img_mask = None
        rows = None
        cols = None
        ground_truth_labels = None

        # then validate contents
        if mask_type:
            if mask_type == MaskTypeEnum.QA:
                img_mask, rows, cols, ground_truth_labels = _makepatch_quick_annotator_mask(img_mask_path,img_csv_path)
            elif mask_type == MaskTypeEnum.Binary:
                img_mask, rows, cols, ground_truth_labels = _makepatch_binary_mask(img_mask_path,img_csv_path)
            elif mask_type == MaskTypeEnum.Indexed:
                img_mask, rows, cols, ground_truth_labels = _makepatch_index_mask(img_mask_path,img_csv_path)
            elif mask_type == MaskTypeEnum.Labeled:
                img_mask, rows, cols, ground_truth_labels = _makepatch_labeled_mask(img_mask_path,img_csv_path)
        else:
            img_mask = np.ones((img.shape[0], img.shape[1]))
            if img_csv_path:
                rows, cols, ground_truth_labels = _process_csvlabels(img_csv_path)
            else:
                idxs = np.asarray(range((imgshape_orig[0] - patchsize) * (imgshape_orig[1] - patchsize))).reshape(
                    np.asarray(imgshape_orig)[0:2] - patchsize)
                # idx_out = sklearn.feature_extraction.image.extract_patches(idxs, (patchsize, patchsize), patchsize)
                idx_out = extract_patches(idxs, (patchsize, patchsize), patchsize)
                idx_out = idx_out[:, :, 0, 0]
                idx_out = idx_out.reshape(-1)
                rows, cols = np.unravel_index(idx_out, idxs.shape)
                rows += patchsize // 2 + patchsize  # want to get into the center of the patch + compensate for padding
                cols += patchsize // 2 + patchsize  # want to get into the center of the patch + compensate for padding
                ground_truth_labels = _generate_default_gtlabels(rows)

        print(f"num rows {len(rows)}")

        for i, (r, c, ground_truth_label) in enumerate(zip(rows, cols, ground_truth_labels)):
            r = int(r)
            c = int(c)
            patch = img[r - patchsize // 2:r + patchsize // 2, c - patchsize // 2:c + patchsize // 2, :]
            patch_mask = img_mask[r - patchsize // 2:r + patchsize // 2, c - patchsize // 2:c + patchsize // 2]


            #remove all objects not of the center id
            cval = patch_mask[patch_mask.shape[0]//2,patch_mask.shape[1]//2]
            if not cval:
                if find_nearest_non_black_pixel(patch_mask, (patchsize//2,patchsize//2)) is not None:
                    newr,newc=find_nearest_non_black_pixel(patch_mask, (patchsize//2,patchsize//2))
                    cval = patch_mask[newr,newc]
                else:
                    error_patch[image_path] = error_patch.get(image_path,0) + 1
                    print(f"Error Patches : {error_patch}")
            patch_mask= patch_mask==cval

            hdf5_file.root.patch.append(patch[None, ::])
            hdf5_file.root.mask.append(patch_mask[None, ::])

            hdf5_file.root.imgID.append([int(imageid)])
            hdf5_file.root.patch_row.append([r - patchsize])  # compensate for padding
            hdf5_file.root.patch_column.append([c - patchsize])

            hdf5_file.root.prediction.append([-1])
            hdf5_file.root.pred_score.append([0])
            hdf5_file.root.ground_truth_label.append([ground_truth_label])

            hdf5_file.root.embed_x.append([-1])
            hdf5_file.root.embed_y.append([-1])

    nobjects = hdf5_file.root.imgID.shape[0]
    hdf5_file.close()

    if error_patch:
        error_patch_log = f"./projects/{project_name}/error_patch_details.txt"
        try:
            with open(error_patch_log, "w") as f:
                f.write('Image_Path'+args.str_delimiter+'No_of_Patches_Missed\n')
                for key in error_patch.keys():
                    f.write("%s%s%s\n" % (key, args.str_delimiter,error_patch[key]))
        except IOError:
            print("I/O error")
        print(f"USER: Done making patches, with missed patches log file saved in {error_patch_log}!", flush=True)
    else:
        print(f"USER: Done making patches !", flush=True)

    print(f"USER: Total number of objects now in database  = {nobjects}.", flush=True)
    print(f"RETVAL: {json.dumps({'image_list': fnames})}", flush=True)


except:
    track = traceback.format_exc()
    track = track.replace("\n", "\t")
    print(f"ERROR: {track}", flush=True)
    sys.exit(1)


