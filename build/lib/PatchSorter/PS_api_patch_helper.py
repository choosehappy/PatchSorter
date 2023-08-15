import base64
import uuid
import os
import logging
import json

from datetime import datetime

import cv2
import numpy as np
import tables
from flask import current_app, jsonify, request, make_response
from shapely.geometry import Polygon

from PS_config import config
from PS_db import Image, Project, db, Metrics, get_filtered_ids, SearchCache, FilterPlot,get_annotations_percent

from PS_searchtree_store import SearchResultStore, SearchTreeStore

from scipy.spatial import distance
from time import perf_counter
from PS_utils import mutex


# from multiprocessing import Lock

# mutex = Lock()

##Api Implementation.
# @api_ns_patch.route("/api/<project_name>/patch/<patch_id>", methods=["GET"])
def get_patch_data(project_name, patch_id):
    # TODO: needs error checking, project + patch id need to exist
    pytableLocation = f"./projects/{project_name}/patches_{project_name}.pytable"
    if not os.path.isfile(pytableLocation):
        return make_response(jsonify(error="Embedding pytable file does not exist"), 400)
    patch_ids = patch_id.split(",")
    with mutex:
        with tables.open_file(pytableLocation, mode='a') as hdf5_file:
            patch_list = []
            for id in patch_ids:
                patch = int(id)
                patch_obj = {'patch_id': patch, 'imgID': hdf5_file.root.imgID[patch].item(),
                             'patch_row': hdf5_file.root.patch_row[patch].item(),
                             'patch_column': hdf5_file.root.patch_column[patch].item(),
                             'prediction': hdf5_file.root.prediction[patch].item(),
                             'ground_truth_label': hdf5_file.root.ground_truth_label[patch].item(),
                             'predscore': hdf5_file.root.pred_score[patch].item(),
                             'embed_x': hdf5_file.root.embed_x[patch].item(),
                             'embed_y': hdf5_file.root.embed_y[patch].item()}
                patch_list.append(patch_obj)
    return make_response(jsonify(patch_list), 200)


# - End point to retrieve the patch image for the mouse over event.
# @api_ns_patch.route("/api/<project_name>/patch/<patch_id>/image", methods=["GET"])
def get_patch_image(project_name, patch_id):
    # TODO: needs error checking, project + patch id need to exist
    proj = db.session.query(Project).filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)
    pytableLocation = f"./projects/{project_name}/patches_{project_name}.pytable"
    if not os.path.isfile(pytableLocation):
        return make_response(jsonify(error="Embedding pytable file does not exist"), 400)

    with mutex:
        with tables.open_file(pytableLocation, mode='r') as hdf5_file:
            img = hdf5_file.root.patch[int(patch_id), ::].squeeze()

    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    # Was using this to save patch images for the new Patch Image Search Feature.
    # basedir = f"./projects/{project_name}/"
    # cv2.imwrite(basedir+"img_"+patch_id+".png", img)
    success, img_encoded = cv2.imencode('.png', img)

    response = make_response(img_encoded.tobytes())
    response.headers['Content-Type'] = 'image/png'
    response.headers['Content-Disposition'] = f'inline; filename = "{patch_id}.png"'
    return response


# @api_ns_patch.route("/api/<project_name>/patch/<patch_id>/context", methods=["GET"])
def get_patch_context_image(project_name, patch_id):
    # TODO: needs error checking, project + patch id need to exist
    proj = db.session.query(Project).filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)
    pytableLocation = f"./projects/{project_name}/patches_{project_name}.pytable"
    if not os.path.isfile(pytableLocation):
        return make_response(jsonify(error="Embedding pytable file does not exist"), 400)

    with mutex:
        with tables.open_file(pytableLocation, mode='r') as hdf5_file:
            c = hdf5_file.root.patch_column[int(patch_id)]
            r = hdf5_file.root.patch_row[int(patch_id)]
            imgid = hdf5_file.root.imgID[int(patch_id)]

    imageobj = db.session.query(Image.id, Image.img_name, Image.img_path).filter(Image.id == int(imgid)).first()
    img = cv2.imread(imageobj.img_path)

    contextsize = config.getint('frontend', 'context_patch_size', fallback=128)
    img = np.pad(img, [(contextsize, contextsize), (contextsize, contextsize),[0,0]], mode="constant", constant_values=0)
    r+=contextsize #allow for cropping around center of object, even if it is on the edge
    c+=contextsize #visually this will make the object in the middle of the ROI

    img = img[max(0, r - contextsize // 2):min(img.shape[0], r + contextsize // 2),
          max(0, c - contextsize // 2):min(img.shape[1], c + contextsize // 2), :]
    success, img_encoded = cv2.imencode('.png', img)

    response = make_response(img_encoded.tobytes())
    response.headers['Content-Type'] = 'image/png'
    response.headers['Content-Disposition'] = f'inline; filename = "{patch_id}_context.png"'
    return response


# - End point to retrieve the patch mask for the mouse over event.
# @api_ns_patch.route("/api/<project_name>/patch/<patch_id>/mask", methods=["GET"])
def get_patch_mask(project_name, patch_id):
    # TODO: needs error checking, project + patch id need to exist
    proj = db.session.query(Project).filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)
    pytableLocation = f"./projects/{project_name}/patches_{project_name}.pytable"
    if not os.path.isfile(pytableLocation):
        return make_response(jsonify(error="Embedding pytable file does not exist"), 400)
    with mutex:
        with tables.open_file(pytableLocation, mode='r') as hdf5_file:
            img = hdf5_file.root.mask[int(patch_id), ::].squeeze()

    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    success, img_encoded = cv2.imencode('.png', img * 255)

    response = make_response(img_encoded.tobytes())
    response.headers['Content-Type'] = 'image/png'
    response.headers['Content-Disposition'] = f'inline; filename = "{patch_id}.png"'
    return response


# - End point to update ground truth labels in pytables.
# @api_ns_patch.route("/api/<project_name>/patch/<patch_id>/ground_truth", methods=["PUT"])
def update_ground_truth(project_name, patch_id):
    proj = db.session.query(Project).filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)

    pytableLocation = f"./projects/{project_name}/patches_{project_name}.pytable"
    if not os.path.isfile(pytableLocation):
        return make_response(jsonify(error="Embedding pytable file does not exist"), 400)
    patch_ids = patch_id.split(",")
    if 'gt' not in request.args:
        return make_response(jsonify(error="gt variable not set"), 400)

    gt = request.args.get('gt', default=-1, type=int)
    with mutex:
        with  tables.open_file(pytableLocation, mode='a') as hdf5_file:
            for patch in patch_ids:
                hdf5_file.root.prediction[int(patch)] = gt,
                hdf5_file.root.ground_truth_label[int(patch)] = gt

            gt_label = hdf5_file.root.ground_truth_label[:]

    object_count, percent_annotated,percent_dist = get_annotations_percent(gt_label)

    no_id = len(patch_ids)
    new_metric = Metrics(projId=proj.id, label_update_time=datetime.utcnow(),
                             no_of_objects_labelled=no_id)
    db.session.add(new_metric)
    db.session.commit()

    return make_response(jsonify(patch_id=patch_id, ground_truth=gt,object_count=object_count,
                                 percent_annotated=percent_annotated,percent_dist=percent_dist), 200)


def update_label_metrics(no_patchs_labelled, projId):
    if no_patchs_labelled > 0:
        current_app.logger.info('Updating Metrics in database:')
        # create a metrics row:


# @SearchCache.memoize()
def patch_by_polygon(project_name, polygonstring, plot_by, filter_by, class_by):
    points = [point.strip().split(' ') for point in polygonstring.replace("M", "").split("L")]
    points = np.asarray(points).astype(np.float)
    try:
        polygon = Polygon(points)
    except:
        return make_response(jsonify(message="Lasso not done correctly"), 400)
    tree = SearchTreeStore[project_name]
    if tree is None:
        return make_response(jsonify(error="Search table does not exist"), 400)
    hits = tree.query(polygon)  # the .query ofthe STree returns not the points within the polygon made by the lasso,
    # but the points within the extent of the polygon made by the lasso.
    # The extent in this case is essentially the bounding box.
    # https://shapely.readthedocs.io/en/stable/manual.html#strtree.STRtree.strtree.query

    if not hits:
        return make_response(jsonify(message="No Patches obtained, please lasso over the points."), 400)

    idx = [hit.id for hit in hits if
           hit.intersects(polygon)]  # --- note this should be stored in memory on server side in a cache
    # idx = [int(hit.id) for hit in hits]
    if filter_by != int(FilterPlot.ALL) or class_by != int(FilterPlot.ALL):
        idx = get_filtered_ids(idx, plot_by, filter_by, class_by, project_name)

    embedkey = str(uuid.uuid4())
    SearchResultStore[embedkey] = idx
    return make_response(jsonify(embeddingCnt=len(idx), embeddingKey=embedkey), 200)


# @SearchCache.memoize()
def patch_by_page(project_name, embedKey, pageNo, pageLimit):
    start = int(pageLimit) * int(pageNo)
    next = int(pageLimit) * (int(pageNo) + 1)
    allids = SearchResultStore[embedKey]
    # if next > len(allids):
    #     next = len(allids)
    end = min(next, len(allids))
    patch_ids = allids[start:end]
    pytableLocation = f"./projects/{project_name}/patches_{project_name}.pytable"
    with mutex:
        with tables.open_file(pytableLocation, mode='r') as hdf5_file:
            rowCount = np.arange(int(hdf5_file.root.embed_x.shape[0]))
            patch_data = np.asarray([
                rowCount[patch_ids],
                hdf5_file.root.embed_x[patch_ids],
                hdf5_file.root.embed_y[patch_ids],
                hdf5_file.root.ground_truth_label[patch_ids],
                hdf5_file.root.prediction[patch_ids],
                hdf5_file.root.pred_score[patch_ids],
            ]).transpose().tolist()
    #         image_dict = {}
    #         for id in patch_ids:
    #             image_dict[id] = base64.b64encode(cv2.imencode('.png',cv2.cvtColor(hdf5_file.root.patch[int(id), ::].squeeze(), cv2.COLOR_RGB2BGR))[1]).decode()
    # return make_response(jsonify(patch_data=patch_data,patch_images=image_dict), 200)
    return make_response(jsonify(patch_data=patch_data), 200)


def closeset_patch(project_name, image_id, x, y):
    t_start = perf_counter()
    pytableLocation = f"./projects/{project_name}/patches_{project_name}.pytable"
    with mutex:
        with tables.open_file(pytableLocation, mode='r') as hdf5_file:
            patch_idxs = np.nonzero(hdf5_file.root.imgID[:] == image_id)[0]
            rows = hdf5_file.root.patch_row[patch_idxs]
            cols = hdf5_file.root.patch_column[patch_idxs]

            patch_centroids_xy = np.stack((cols, rows), axis=1)
            query_xy = (x, y)
            # https://codereview.stackexchange.com/a/134918
            closest = distance.cdist([query_xy], patch_centroids_xy).argmin()

            closest_patch_idx = patch_idxs[closest]
            closest_patch_row = rows[closest]
            closest_patch_col = cols[closest]
            closest_patch_prediction = hdf5_file.root.prediction[closest_patch_idx]
            closest_patch_ground_truth = hdf5_file.root.ground_truth_label[closest_patch_idx]
    t_end = perf_counter()

    return make_response(
        jsonify(
            patch_id=int(closest_patch_idx),
            Y=int(closest_patch_row),
            X=int(closest_patch_col),
            prediction=int(closest_patch_prediction),
            ground_truth=int(closest_patch_ground_truth),
            query_ms=round(1000 * (t_end - t_start))),
        200)
