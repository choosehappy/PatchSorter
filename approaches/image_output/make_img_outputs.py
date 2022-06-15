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
import matplotlib.pyplot as plt
import numpy as np
import skimage.measure
import sklearn.feature_extraction.image
from skimage.segmentation import find_boundaries
import tables
from tqdm.autonotebook import tqdm
import matplotlib

cmap = matplotlib.cm.get_cmap('Set1')


def find_nearest_non_black_pixel(img, target):
    nonzero = np.argwhere(img>0)
    distances = np.sqrt((nonzero[:,0] - target[0]) ** 2 + (nonzero[:,1] - target[1]) ** 2)
    nearest_index = np.argmin(distances)
    return nonzero[nearest_index]


# +
try:
    parser = argparse.ArgumentParser(description='Put patches into pytable for PatchSorter')
    parser.add_argument('-t', '--output_type', help="what output to make, {pred,gt}", default="gt", type=str)
    parser.add_argument('-o', '--outdir', help="outputdir, default ./output/", default="./output/", type=str)
    parser.add_argument('--overlay', action="store_true", help="overlay on original image")
    parser.add_argument('--overlayids', action="store_true", help="overlay on original image")
    parser.add_argument('csvfile', help="CSV file of files to import of format: imageid,image_path,image_mask_path,image_csv_path")
    parser.add_argument('pytableoutput', help="pytable to either append or create")

    
    #args = parser.parse_args([r"C:\temp\PatchSorter\projects\test\image_details.csv",r"C:\temp\PatchSorter\projects\test\patches_test.pytable","-tpred","--overlay"])
    args = parser.parse_args()
    if os.path.exists(args.pytableoutput):
        hdf5_file = tables.open_file(args.pytableoutput, mode='a')
        patchsize = hdf5_file.root.patch[0,:,:].shape[0]


        basedir=f"{args.outdir}/{args.output_type}/"
        if not os.path.exists(basedir):
            os.makedirs(basedir)

        basediroverlay=f"{args.outdir}/{args.output_type}/overlay/"
        if not os.path.exists(basediroverlay):
            os.makedirs(basediroverlay)


        fnames = []
        for line in open(args.csvfile, 'r'):
            print(line.strip())
            sline = line.strip().split(",")
            imageid = sline[0]
            image_path = sline[1]
            fnames.append(image_path)

            # --- mask work
            if len(sline) > 2 and len(sline[2]) > 0:  # image_mask is set
                patch_type = False
                image_mask_path = sline[2]
                img_mask = cv2.cvtColor(cv2.imread(image_mask_path), cv2.COLOR_BGR2RGB)

                if np.any(~((img_mask[:, :, 0] == img_mask[:, :, 1]) & (img_mask[:, :, 1] == img_mask[:, :, 2]))):
                    # qupath mask, convert image_mask to binary mask (should only require extracting the right channel from the image)
                    img_mask = img_mask[:, :, 1].squeeze()
                else:
                    img_mask = img_mask[:, :, 0].squeeze()  # convery 3 channel grayscale to 1 channel gray scale

                if len(np.unique(img_mask)) == 2:  # is of type binary, use skimage label on image_mask
                    img_mask = skimage.measure.label(img_mask)
            else:
                patch_type = True

            img = cv2.cvtColor(cv2.imread(image_path), cv2.COLOR_BGR2RGB)
            img_mask_out=np.zeros(img.shape,dtype=np.uint8)

            for idx in np.argwhere(hdf5_file.root.imgID[:] ==int(imageid)):
                r=int(hdf5_file.root.patch_row[idx])
                c=int(hdf5_file.root.patch_column[idx])
                val = hdf5_file.root.prediction[idx] if 'pred' in args.output_type else hdf5_file.root.ground_truth_label[idx]
                cval = cmap(val)[0][0:3]*255 if (val!=-1) else np.asarray([50,50,50])
                if patch_type:
                    img_mask_out[r - patchsize // 2:r + patchsize // 2, c - patchsize // 2:c + patchsize // 2] = cval
                else: 
                    rc_idx  = img_mask[r,c]
                    if not rc_idx :
                        newr,newc=find_nearest_non_black_pixel(img_mask, (r,c))
                        rc_idx  = img_mask[newr,newc]
                
                    img_mask_out[img_mask==rc_idx]=cval

            cv2.imwrite(basedir+os.path.basename(image_path),cv2.cvtColor(img_mask_out, cv2.COLOR_RGB2BGR) )

            #--- if overlay is requested
            if args.overlay:
                img_mask_out_dilated=cv2.dilate(img_mask_out,kernel = np.ones((4,4),np.uint8))
                boundary = img_mask_out_dilated.any(axis=2) * ~img_mask_out.any(axis=2)
                img[boundary]=img_mask_out_dilated[boundary]

                cv2.imwrite(basediroverlay+os.path.basename(image_path),cv2.cvtColor(img, cv2.COLOR_RGB2BGR))

            if args.overlayids:
                # to obtain the name of the image without extension
                basepath, filename = os.path.split(image_path)
                filebase, fileext = os.path.splitext(filename)
                for idx in np.argwhere(hdf5_file.root.imgID[:] == int(imageid)):
                    r = int(hdf5_file.root.patch_row[idx])
                    c = int(hdf5_file.root.patch_column[idx])
                    x = int(hdf5_file.root.embed_x[idx])
                    y = int(hdf5_file.root.embed_y[idx])
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    text_location = (c, r)
                    fontScale = 0.40
                    fontColor = (0, 255, 0)
                    thickness = 1
                    idx_disp = str(int(idx))
                    cv2.putText(img, idx_disp,text_location,
                                font,fontScale,fontColor,thickness)
                cv2.imwrite(basediroverlay + filebase+'_overlayid.png', cv2.cvtColor(img, cv2.COLOR_RGB2BGR))

        hdf5_file.close()
        print(f"USER: Done making output !", flush=True)

        print(f"RETVAL: {json.dumps({'csvfile': args.csvfile,'image_list': fnames})}", flush=True)

except:
    track = traceback.format_exc()
    track = track.replace("\n", "\t")
    print(f"ERROR: {track}", flush=True)
    sys.exit(1)
