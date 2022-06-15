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

import dill as pickle
from shapely.geometry import box
from shapely.geometry import MultiPoint
from shapely.geometry import Point
from shapely.strtree import STRtree
import tables
import numpy as np

searchdbfile=r"C:\temp\PatchSorter\projects\searcjtest\searchtree_searcjtest.pkl"
[searchtree,ids] = pickle.load(open(searchdbfile, "rb" ))

hdf5_file= tables.open_file(r"C:\temp\PatchSorter\projects\searcjtest\patches_searcjtest.pytable", mode='r')

    for id, geom in zip(ids, searchtree._geoms):
        geom.id = int(id)  # https://github.com/Toblerity/Shapely/issues/1033


searchtile  = box(-100,-100,100,100)
hits=searchtree.query(searchtile)

xy=[[hit.x,hit.y]for hit in hits]

xy=np.asarray(xy)

xy.shape

xx=np.linspace(xy[:,0].min(),xy[:,0].max(),num=1000)
yy=np.linspace(xy[:,1].min(),xy[:,1].max(),num=1000)

hdf5_file.root.embed_x[:].min()

H=np.histogram2d(xy[:,0],xy[:,1],[xx,yy]) #--- fast , 24 ms
#H=np.histogram2d(hdf5_file.root.embed_x,hdf5_file.root.embed_y,[xx,yy]) #-- slow 8.8s

H[0].sum()

import matplotlib.pyplot as plt
# %matplotlib notebook

plt.imshow(H[0])

refinedsearchtree = STRtree(hits)

len(hits)
bb=MultiPoint(hits).bounds

X,Y = np.mgrid[bb[0]:bb[2]:100j, bb[1]:bb[3]:100j]

for x,y in zip(X.flatten(),Y.flatten()):
    p=Point(x,y)
    hits=refinedsearchtree.query(p.buffer(10))
    print(p)

for x in np.linspace(bb[0],bb[2]):a
    print(x)
