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

import tables
import dill as pickle
from shapely.geometry import Point
from shapely.strtree import STRtree

# +
try:
    
    parser = argparse.ArgumentParser(description='Put patches into pytable for PatchSorter')
    parser.add_argument('pytableoutput', help="pytable to either append or create")
    parser.add_argument('searchoutput', help="pytable to either append or create")

    #args = parser.parse_args([r"C:\temp\PatchSorter\projects\chuv_rando\patches_chuv_rando.pytable",
    #                            r"C:\temp\PatchSorter\projects\chuv_Rando3\searchtree.pkl"])
    args = parser.parse_args()

    searchfile = args.searchoutput
    hdf5_file = tables.open_file(args.pytableoutput, mode='r')
    points = [Point(x, y) for x, y in zip(hdf5_file.root.embed_x[:], hdf5_file.root.embed_y[:])]
    hdf5_file.close()
    for i in range(len(points)):
        points[i].id = i
    searchtree = STRtree(points)
    ids = [g.id for g in searchtree._geoms[:]]
    pickle.dump([searchtree, ids], open(searchfile, 'wb'))  # --- https://github.com/Toblerity/Shapely/issues/1033

    print(f"USER: Done making search database!", flush=True)
    print(f"RETVAL: Success", flush=True) #--- should very much check this, anything more important need to be done?
        
except:
    track = traceback.format_exc()
    track = track.replace("\n", "\t")
    print(f"ERROR: {track}", flush=True)
    sys.exit(1)
