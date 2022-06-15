import gc
import glob
import json
import logging
import os
import sys
import csv
from datetime import datetime
import numpy as np
from time import perf_counter

import functools
import sqlalchemy
import tables
from flask import jsonify, request, make_response, current_app
from shapely.geometry import box
from sklearn.neighbors import KDTree

from PS_config import config, get_database_uri
from PS_db import Project, Job, db, Labelnames, FilterPlot
from PS_db import get_latest_modelid, get_images, get_objects_details, get_filtered_ids, SearchCache
from PS_pool import pool_run_script, update_completed_job_status
from PS_searchtree_store import SearchTreeStore
### Obtaining Mutex from Utils####
# from multiprocessing import Lock
from PS_utils import mutex

# mutex = Lock()
jobs_logger = logging.getLogger('jobs')


##Api Implementation

def getconfig():  # Front end can now keep track of the last lines sent and request all the "new" stuff
    allsections = dict()
    for section in config.sections():
        sectionitems = []
        for items in config[section].items():
            sectionitems.append(items)
        allsections[section] = sectionitems
    return jsonify(allsections)


def make_patches(project_name):
    # pull this project from the database:
    current_app.logger.info(f'Getting project info from database for project {project_name}.')
    project = db.session.query(Project).filter_by(name=project_name).first()
    if project is None:
        current_app.logger.warn(f'Unable to find {project_name} in database. Returning HTML response code 400.')
        return make_response(jsonify(error=f"Project {project_name} does not exist"), 400)

    csvfileName = f"./projects/{project_name}/image_details.csv";
    str_delimiter = config.get('image_details', 'delimitby', fallback=',')
    if str_delimiter == ',':
        csvfileName = f"./projects/{project_name}/image_details.csv";
    else:
        csvfileName = f"./projects/{project_name}/image_details.txt";
    current_app.logger.info(f'Saving to {csvfileName}:')
    # -- Changed the f.write to not have mask and csv path if None 10/22/2020
    images = get_images(project.id)
    csv_colnames = ['mask_type','image_id','img_path','mask_path','csv_path']
    with open(csvfileName, "w",newline='') as f:
        w = csv.DictWriter(f, csv_colnames,delimiter=str_delimiter)
        # w.writeheader()  #Can enable headers if needed
        for image in images:
            if image.make_patches_time:
                continue
            details = {'mask_type': image.mask_type, "image_id": image.id,'img_path':image.img_path,
                       'mask_path':image.mask_path,'csv_path':image.csv_path}
            w.writerow(details)


    current_app.logger.info("Image details file is ready")
    # get config properties:
    patchsize = config.getint('make_patches', 'patchsize', fallback=32)
    makepatch_script_name = config.get('make_patches', 'makepatch_script_name',
                                       fallback='./approaches/make_patches/make_patch_database.py')
    pytablefile = f"./projects/{project_name}/patches_{project_name}.pytable";
    # get the command:
    full_command = [sys.executable, f"{makepatch_script_name}", f"{project_name}",
                    f"-p{patchsize}", f"{csvfileName}", f"{pytablefile}", f"{str_delimiter}"]

    # close the db session and note that patches_computed is true:
    db.session.commit()

    # run the command asynchronously
    command_name = "make_patches"
    return pool_run_script(project_name, command_name, full_command, callback=make_patches_callback)

    # return jsonify(success=True), 204


# -- will be invoked post make_patches_database.py is executed.
def make_patches_callback(result):
    # update the job status in the database:
    update_completed_job_status(result)

    retval, jobid = result
    engine = sqlalchemy.create_engine(get_database_uri())
    dbretval = engine.connect().execute(f"select procout from jobid_{jobid} where procout like 'RETVAL:%'").first()
    if dbretval is None:
        # no retval, indicating make_patches didn't get to the end, leave everything as is
        engine.dispose()
        return

    retvaldict = json.loads(dbretval[0].replace("RETVAL: ", ""))
    for img in retvaldict["image_list"]:
        engine.connect().execute(f"update image set make_patches_time = datetime('now') where img_path= :img", img=img)

    # if it was successful, mark the training time in the database:

    if retval == 0:
        jobs_logger.info('Marking make_patches time in database:')
        projid = engine.connect().execute(f"select projId from job where id = :jobid", jobid=jobid).first()[0]
        engine.connect().execute(f"update project set make_patches_time = datetime('now') where id = :projid",
                                 projid=projid)

    engine.dispose()


# - train_dl for the patches.
def train_dl(project_name):
    proj = Project.query.filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)
    current_app.logger.info(f'About to train a new transfer model for {project_name}')

    current_modelid = get_latest_modelid(project_name)
    output_model_path = f"./projects/{project_name}/models/{current_modelid + 1}/"
    current_app.logger.info(f'New model path = {output_model_path}')

    # get config properties:
    train_script_name = config.get('train_dl', 'train_script_name', fallback="./approaches/simclr/train_dl_simclr.py")
    num_epochs = config.getint('train_dl', 'numepochs', fallback=1000)
    num_epochs_earlystop = config.getint('train_dl', 'num_epochs_earlystop', fallback=-1)
    numepochs_inital = config.getint('train_dl', 'numepochs_inital', fallback=100)
    minlossearlystop = config.getfloat('train_dl', 'minimum_loss_earlystop', fallback=.001)
    unlabeled_percent = config.getfloat('train_dl', 'unlabeled_percent', fallback=2)
    num_min_epochs = config.getint('train_dl', 'num_min_epochs', fallback=300)
    batch_size = config.getint('train_dl', 'batchsize', fallback=32)
    patch_size = config.getint('train_dl', 'patchsize', fallback=256)
    codesize = config.getint('common', 'codesize', fallback=32)
    num_workers = config.getint('train_dl', 'numworkers', fallback=0)
    fillbatch = config.getboolean('train_dl', 'fillbatch', fallback=False)
    maskpatches = config.getboolean('train_dl', 'maskpatches', fallback=False)
    prev_model_init = config.getboolean('train_dl', 'prev_model_init', fallback=None)

    pytablefile = f"./projects/{project_name}/patches_{project_name}.pytable"

    # get the command to retrain the model:
    full_command = [sys.executable, f"{train_script_name}",
                    f"{project_name}",
                    f"{pytablefile}", f"{int(proj.no_of_label_type)}",
                    f"-p{patch_size}",
                    f"-c{codesize}",
                    f"-n{num_epochs}",
                    f"-s{num_epochs_earlystop}",
                    f"-l{num_min_epochs}",
                    f"-u{unlabeled_percent}",
                    f"-b{batch_size}",
                    f"-o{output_model_path}",
                    f"-r{num_workers}",
                    f"--numepochsinital", f"{numepochs_inital}",
                    f"--minlossearlystop", f"{minlossearlystop}"]

    if fillbatch:
        full_command.append("--fillbatch")

    if maskpatches:
        full_command.append("--maskpatches")

    if prev_model_init:
        prev_model_fname = glob.glob(f"./projects/{project_name}/models/{current_modelid}/best*.pth")
        if prev_model_fname:
            full_command.append(f"-m{prev_model_fname[0]}")

    current_app.logger.info(f'Training command = {full_command}')

    # run the script asynchronously:
    command_name = "train_dl"
    return pool_run_script(project_name, command_name, full_command, callback=train_dl_callback)


def train_dl_callback(result):
    # update the job status in the database:
    update_completed_job_status(result)

    jobid = result[1]
    engine = sqlalchemy.create_engine(get_database_uri())

    dbretval = engine.connect().execute(f"select procout from jobid_{jobid} where procout like 'RETVAL:%'").first()
    if dbretval is None:
        # no retval, indicating superpixel didn't get to the end, leave everything as is
        engine.dispose()
        return

    retvaldict = json.loads(dbretval[0].replace("RETVAL: ", ""))
    projname = retvaldict["project_name"]
    iteration = retvaldict["iteration"]

    engine.connect().execute(
        f"update project set iteration  = :iteration, train_dl_time = datetime('now') where name = :projname",
        projname=projname, iteration=iteration)
    engine.dispose()


# -------------------------------------------- EMBEDDING WORK
# - End point to obtain the embed values.
# if needed we could have a train and embed endpoint and not have two , but will confirm that later.
def make_embed(project_name):
    proj = db.session.query(Project).filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)

    if proj.train_dl_time is None and proj.iteration == 0:
        error_message = f'The base model 0 of project {project_name} was overwritten when Retrain Model 0 started.\n ' \
                        f'Please wait until the Retrain Model 0 finishes. '
        current_app.logger.warn(error_message)
        return make_response(jsonify(error=error_message), 400)

    pytablefile = f"./projects/{project_name}/patches_{project_name}.pytable"
    if not os.path.isfile(pytablefile):
        return make_response(jsonify(error="pytable file does not exist, consider making patches first"), 400)

    modelid = request.args.get('modelid', default=get_latest_modelid(project_name), type=int)
    outdir = f"./projects/{project_name}/models/{modelid}"

    embed_script_name = config.get('embed', 'embed_script_name', fallback='./approaches/simclr/make_embed_simclr.py')
    maskpatches = config.getboolean('embed', 'maskpatches', fallback=False)
    batch_size = config.getint('embed', 'batchsize', fallback=32)
    patch_size = config.getint('embed', 'patchsize', fallback=32)
    codesize = config.getint('common', 'codesize', fallback=32)
    dimredux = config.getint('embed', 'dimredux', fallback=-1)
    num_workers = config.getint('embed', 'numworkers', fallback=0)
    semisupervised = config.getboolean('embed', 'semisupervised', fallback=True)
    save_features = config.getboolean('embed', 'save_features', fallback=False)

    # get the command:
    full_command = [sys.executable, f"{embed_script_name}", f"{project_name}", f"-o{outdir}",
                    f"{pytablefile}", f"-b{batch_size}", f"-p{patch_size}", f"-c{codesize}",
                    f"-d{dimredux}", f"-r{num_workers}", f"{proj.no_of_label_type}"]

    if maskpatches:
        full_command.append("--maskpatches")

    if semisupervised:
        full_command.append("--semisupervised")

    if save_features:
        full_command.append("--save_features")

    current_app.logger.info(f'Full command = {str(full_command)}')

    db.session.commit()
    getHits.cache_clear()

    # run the command asynchronously:
    command_name = "make_embed"
    return pool_run_script(project_name, command_name, full_command, callback=make_embed_callback)


# - Call back method to update the embed_iteration time post make_embed is complete
def make_embed_callback(result):
    # update the job status in the database:
    update_completed_job_status(result)
    jobid = result[1]
    engine = sqlalchemy.create_engine(get_database_uri())

    dbretval = engine.connect().execute(f"select procout from jobid_{jobid} where procout like 'RETVAL:%'").first()
    if dbretval is None:
        # no retval, indicating  didn't get to the end, leave everything as is
        engine.dispose()
        return
    retvaldict = json.loads(dbretval[0].replace("RETVAL: ", ""))
    projname = retvaldict["project_name"]
    modelid = retvaldict["modelid"]
    xmax = retvaldict["xmax"]
    xmin = retvaldict["xmin"]
    ymax = retvaldict["ymax"]
    ymin = retvaldict["ymin"]

    engine.connect().execute(
        f"update project set embed_iteration = :modelid, xmax = :xmax, xmin = :xmin, ymax = :ymax, ymin = :ymin where name = :projname",
        projname=projname,
        modelid=modelid, xmax=xmax, xmin=xmin, ymax=ymax, ymin=ymin)
    engine.dispose()


# - Endpoint created for update label Names
# @api_project.route('/api/<project_name>/labelnames', methods=["UPDATE"])
def update_label_names(project_name, labels):
    current_app.logger.info(
        f'Updating Labels. Project = {project_name}')
    # labelList = json.loads(request.args.get("labels"))
    labelList = labels

    for newlabel in labelList:
        labels = db.session.query(Labelnames.id, Labelnames.label_id, Labelnames.label_name). \
            filter(Labelnames.id == newlabel["id"]).first()
        if labels is None:
            return make_response(jsonify(error=f"labels {project_name} doesn't exist"), 400)
        if (labels.label_name != newlabel["label_name"]):
            labelUpdate = db.session.query(Labelnames).filter_by(id=newlabel["id"]). \
                update({Labelnames.label_name: newlabel["label_name"].capitalize()})

            current_app.logger.info(f'Updating {newlabel["label_id"]} in the database:')
    db.session.commit()
    return make_response(jsonify(success=True), 200)


def get_project_status(project_name):
    project = Project.query.filter_by(name=project_name).first()
    if project is None:
        current_app.logger.warn(f'Unable to find {project_name} in database. Returning HTML response code 400.')
        return make_response(jsonify(error=f"Project {project_name} does not exist"), 400)

    object_count, annotated_percent , percent_dist= get_objects_details(project_name)

    return jsonify(success=True, object_count=object_count, percent_annotated=annotated_percent,percent_dist=percent_dist)


def get_job_status(job_id):
    job = Job.query.filter_by(id=job_id).first()
    if job is None:
        current_app.logger.warn(f'Unable to find {job_id} in database. Returning HTML response code 400.')
        return make_response(jsonify(error=f"Job with {job_id} does not exist"), 400)
    # Returning the Status of the job.
    return make_response(jsonify(job_id=job_id, status=job.status, start_date=job.start_date, end_date=job.end_date),
                         200)


def get_points_on_grid(project_name, xmin, xmax, ymin, ymax,plot_by,filter_by,class_by):
    patchsize =  config.get('common','patchsize', fallback=32)

    xyspacing =  int(config.get('show_patches','patchsize_'+patchsize, fallback=10))

    xticks = np.linspace(xmin, xmax, xyspacing).astype(float).round(4)
    yticks = np.linspace(ymin, ymax, xyspacing).astype(float).round(4)
    gridpts = np.meshgrid(xticks, yticks)
    gridpts = np.vstack([np.ravel(g) for g in gridpts])

    maxpoints = request.args.get('maxpoints',
                                 default=int(config.get('embed',
                                                        'maxpoints', fallback=5000)), type=int)
    totalres, providedres, embedding, timing = ranged_embed(project_name,
                                                            round(xmin, 4), round(ymin, 4),
                                                            round(xmax, 4), round(ymax, 4),
                                                            plot_by,filter_by,class_by,maxpoints)

    ## KDTRee Approach STARTS ###

    # converts embedding from list to ndarray picks from embedding all rows and col1 and col2
    points = np.array(embedding)[:, 1:3]
    tree = KDTree(points)
    if tree is None:
        return make_response(jsonify(error="Search table does not exist"), 400)
    start_pts_prc1 = datetime.now()
    pts_dist, pts_ids = tree.query(gridpts.transpose(), k=1)

    # if we want to check based on min distance from grid uncomment below line
    # min_distance = round(np.sqrt((xticks[0] - xticks[1]) ** 2 + (yticks[0] - yticks[1]) ** 2) / 2,2)
    # pts_ids = [int(i) for d, i in zip(pts_dist, pts_ids) if d < min_distance]
    current_app.logger.debug((f'Time to retrieve nearest points on grid: {datetime.now() - start_pts_prc1}'))
    if not np.any(pts_ids):
        return make_response(jsonify(error="No Grid Points retrieved"), 400)

    start_pts_prc2 = datetime.now()
    anim_gridpt_array = [embedding[int(id)] for id in pts_ids]
    current_app.logger.debug((f'DateTime to organize data for frontend: {datetime.now() - start_pts_prc2}'))
    ## KDTRee Approach ENDS ###

    # garbage collect for debugging
    gc.collect()
    return make_response(jsonify(anim_patchids=anim_gridpt_array), 200)

@functools.lru_cache(maxsize=32)
def getHits(tree,xmin, ymin, xmax, ymax):
    searchtile = box(xmin, ymin, xmax, ymax)

    mutex_treequery_init = perf_counter()
    with mutex:
        hits = tree.query(searchtile)
    mutex_treequery_exit = perf_counter()
    tree_query = mutex_treequery_exit - mutex_treequery_init
    current_app.logger.info(f"----->> Time-(getHits) tree_query is {tree_query} seconds")
    idx = np.asarray([hit.id for hit in hits])
    return idx,tree_query


# Will obtain the embedding based on a range
# @SearchCache.memoize()
def ranged_embed(project_name, xmin, ymin, xmax, ymax,plot_by,filter_by, class_by, maxpoints):
    current_app.logger.info(f"Search min is {xmin}, {ymin}, and max is {xmax}, {ymax} and maxpoints {maxpoints}")
    pytableLocation = f"./projects/{project_name}/patches_{project_name}.pytable"
    if not os.path.isfile(pytableLocation):
        return make_response(jsonify(error="Embedding pytable file does not exist"), 400)

    gettreequery_init = perf_counter()
    tree = SearchTreeStore[project_name]
    gettreequery_exit = perf_counter()
    gettree = gettreequery_exit - gettreequery_init
    current_app.logger.info(f"Time-(ranged_embed) get_tree is {gettree} seconds")
    if tree is None:
        return make_response(jsonify(error="Search table does not exist"), 400)

    idx,tree_query = getHits(tree, xmin, ymin, xmax, ymax)

    if filter_by != int(FilterPlot.ALL) or class_by != int(FilterPlot.ALL):
        idx = get_filtered_ids(idx, plot_by, filter_by, class_by, project_name)

    totalres = len(idx)
    if len(idx) > maxpoints:
        idx = np.random.choice(idx, size=maxpoints, replace=False)
    providedres = len(idx)
    mutex_pytablequery_init = perf_counter()
    with mutex:
        with tables.open_file(pytableLocation, mode='r') as hdf5_file:
            # Added rowCount to use it for Patch_id.
            embedding = [ #tolist done seperately to keep the "ints" as "ints"
                idx.tolist(),
                np.around(hdf5_file.root.embed_x[idx].tolist(), 2),
                np.around(hdf5_file.root.embed_y[idx].tolist(), 2),
                hdf5_file.root.ground_truth_label[idx].tolist(),
                hdf5_file.root.prediction[idx].tolist(),
                np.around(hdf5_file.root.pred_score[idx].tolist(), 2)
            ]
        embedding=list(map(list, zip(*embedding)))
    mutex_pytablequery_exit = perf_counter()
    pytable_query = mutex_pytablequery_exit - mutex_pytablequery_init
    current_app.logger.info(f"Time-(ranged_embed) pytable_query is {pytable_query} seconds")

    current_app.logger.info(f"Totalres is {totalres},providedres {providedres}, and embedding is {len(embedding)}")

    timing = {'get_tree': gettree, 'mutex_treequery': tree_query, 'mutex_pytable': pytable_query}
    return totalres, providedres, embedding, timing


def check_proj_exists(project_name):
    project = Project.query.filter_by(name=project_name).first()
    if project is None:
        current_app.logger.warn(f'Unable to find {project_name} in database. Returning HTML response code 400.')
        return make_response(jsonify(error=f"Project {project_name} does not exist"), 400)
    return project


# -- will be invoked for creating searchtree pkl file.
def make_searchdb(project_name):
    # SearchCache.clear()
    # pull this project from the database:
    current_app.logger.info(f'Getting project info from database for project {project_name}.')
    project = db.session.query(Project).filter_by(name=project_name).first()
    if project is None:
        current_app.logger.warn(f'Unable to find {project_name} in database. Returning HTML response code 400.')
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)
    pytablefile = f"./projects/{project_name}/patches_{project_name}.pytable";
    searchdbfile = f"./projects/{project_name}/searchtree_{project_name}.pkl";

    searchdb_script_name = config.get('search_db', 'searchdb_script_name',
                                      fallback='./approaches/search_db/make_search_database.py')
    # get the command:
    full_command = [sys.executable, f"{searchdb_script_name}", f"{pytablefile}", f"{searchdbfile}"]
    # run the command asynchronously
    command_name = "make_searchdb"
    current_app.logger.info(f'output command = {full_command}')
    return pool_run_script(project_name, command_name, full_command, callback=make_searchdb_callback)


def make_searchdb_callback(result):
    # update the job status in the database:
    update_completed_job_status(result)


# - Endpoint to obtain the embed details for the plot with hover. Current not in use, we will use range_embed instead.
# @api_project.route("/api/<project_name>/patch/embed", methods=["GET"])
# def get_embed(project_name):
#     proj = db.session.query(Project).filter_by(name=project_name).first()
#     if proj is None:
#         return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)
#
#     pytableLocation = f"./projects/{project_name}/patches_{project_name}.pytable"
#
#     if not os.path.isfile(pytableLocation):
#         return make_response(jsonify(error="Embedding pytable file does not exist"), 400)
#     with mutex:
#         with tables.open_file(pytableLocation, mode='r') as hdf5_file:
#             # Added rowCount to use it for Patch_id.
#             # rowCount = np.arange(len(hdf5_file.root.embed_x[:])) Changed code to below to improve performance
#             rowCount = np.arange(int(hdf5_file.root.embed_x.shape[0]))
#             embedding = np.asarray([
#                 rowCount[:],
#                 hdf5_file.root.embed_x[:],
#                 hdf5_file.root.embed_y[:],
#                 hdf5_file.root.ground_truth_label[:],
#                 hdf5_file.root.prediction[:],
#                 hdf5_file.root.pred_score[:]
#             ]).transpose().tolist()
#
#     return jsonify(success=True, embedding=embedding)


# Currently not in use as we are not letting a user delete a label.
# @api_project.route('/api/<project_name>/label/<label_id>',
#                    methods=["DELETE"])  # below should be done in a post-processing call
def delete_label(project_name, label_id):
    proj = Project.query.filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)
    # Remove the image from database
    selected_label = db.session.query(Labelnames).filter_by(projId=proj.id, label_id=label_id).first()
    db.session.delete(selected_label)
    db.session.commit()
    return make_response(jsonify(success=True), 204)
