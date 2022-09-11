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

import tables
import numpy as np

t=tables.open_file('patches_rando.pytable',mode='a')

rem=t.root.imgID[:]>=119
keep=t.root.imgID[:]<119

sum(rem)

sum(keep)

# +

hdf5_file = tables.open_file("newone.py", mode='w')
patch_shape = np.array((32, 32, 3))
mask_shape = np.array((32, 32))
filters = tables.Filters(complevel=6,
                         complib='zlib')  # we can also specify filters, such as compression, to improve storage speed

hdf5_file.create_earray(hdf5_file.root, "imgID", tables.UInt16Atom(), shape=[0], chunkshape=[1],
                        filters=filters)
hdf5_file.create_earray(hdf5_file.root, "patch_row", tables.UInt16Atom(), shape=[0], chunkshape=[1],
                        filters=filters)
hdf5_file.create_earray(hdf5_file.root, "patch_column", tables.UInt16Atom(), shape=[0], chunkshape=[1],
                        filters=filters)

hdf5_file.create_earray(hdf5_file.root, "prediction", tables.Int8Atom(), shape=[0], chunkshape=[1],
                        filters=filters)
hdf5_file.create_earray(hdf5_file.root, "ground_truth_label", tables.Int8Atom(), shape=[0], chunkshape=[1],
                        filters=filters)

hdf5_file.create_earray(hdf5_file.root, "pred_score", tables.Float16Atom(), shape=[0], chunkshape=[1],
                        filters=filters)

hdf5_file.create_earray(hdf5_file.root, "embed_x", tables.Float16Atom(), shape=[0], chunkshape=[1],
                        filters=filters)
hdf5_file.create_earray(hdf5_file.root, "embed_y", tables.Float16Atom(), shape=[0], chunkshape=[1],
                        filters=filters)

hdf5_file.create_earray(hdf5_file.root, "patch", tables.UInt8Atom(), shape=np.append([0], patch_shape),
                        chunkshape=np.append([1], patch_shape), filters=filters)
hdf5_file.create_earray(hdf5_file.root, "mask", tables.UInt8Atom(), shape=np.append([0], mask_shape),
                        chunkshape=np.append([1], mask_shape), filters=filters)



# +
hdf5_file.root.imgID.append(t.root.imgID[keep])
hdf5_file.root.patch_row.append(t.root.patch_row[keep])  # compensate for padding
hdf5_file.root.patch_column.append(t.root.patch_column[keep])

hdf5_file.root.prediction.append(t.root.prediction[keep])
hdf5_file.root.pred_score.append(t.root.pred_score[keep])
hdf5_file.root.ground_truth_label.append(t.root.ground_truth_label[keep])

hdf5_file.root.embed_x.append(t.root.embed_x[keep])
hdf5_file.root.embed_y.append(t.root.embed_y[keep])


hdf5_file.root.patch.append(np.asarray(t.root.patch)[keep,::])
hdf5_file.root.mask.append(np.asarray(t.root.mask)[keep,::])
# -

hdf5_file.close()


