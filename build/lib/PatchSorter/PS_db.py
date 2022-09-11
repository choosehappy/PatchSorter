import logging
import os
from multiprocessing import Lock

import numpy as np
import sqlalchemy
import tables
from flask_restless import ProcessingException
from flask_sqlalchemy import SQLAlchemy
from flask import current_app
from sqlalchemy import Text

from PS_config import get_database_uri, config

from flask_admin import Admin
from flask_admin.contrib.sqla import ModelView
from flask_caching import Cache
from PS_utils import mutex
from collections import Counter

from enum import IntEnum
from time import perf_counter
import enum
from sqlalchemy.types import Enum as SQLEnum


# mutex = Lock()
jobs_logger = logging.getLogger('jobs')
_pool = []
db = SQLAlchemy()
SearchCache = Cache(config={'CACHE_TYPE': 'SimpleCache'})

#Enum for constants for Plot filtering.
class FilterPlot(IntEnum):
    ALL = -1
    UNLABELED = 0
    LABELED = 1
    DISCORDANT = 2
    PREDICTION = 1
    GROUNDTRUTH = 2

# Create Flask-SQLALchemy models
#Added a server date to be added automatically for every project created
class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(Text, nullable=False, unique=True)
    description = db.Column(db.Text, default="")
    date = db.Column(db.DateTime, server_default=db.func.now())
    train_dl_time = db.Column(db.DateTime)
    make_patches_time = db.Column(db.DateTime)
    no_of_label_type = db.Column(db.Integer, default=2)
    iteration = db.Column(db.Integer, default=-1)
    embed_iteration = db.Column(db.Integer, default=-2)
    images = db.relationship('Image', backref='project', lazy=True)
    jobs = db.relationship('Job', backref='project', lazy=True)
    xmax = db.Column(db.Float, default=1000)
    xmin = db.Column(db.Float, default=-1000)
    ymax = db.Column(db.Float, default=1000)
    ymin = db.Column(db.Float, default=-1000)


# https://stackoverflow.com/a/51976841
class MaskTypeEnum(str, enum.Enum):
    QA = 'QA'
    Binary = 'Binary'
    Indexed = 'Indexed'
    Labeled = 'Labeled'

    # Setting an import type field in the images table to identify if type of
    # import ('drop' will be used for file uploads or drops) and
    # 'upload' will be used for folder path uploads
class Image(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    projId = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    img_name = db.Column(db.Text)
    img_path = db.Column(db.Text)
    mask_path = db.Column(db.Text)
    mask_type = db.Column(SQLEnum(MaskTypeEnum, create_constraint=True))
    csv_path = db.Column(db.Text)
    height = db.Column(db.Integer)
    width = db.Column(db.Integer)
    nobjects = db.Column(db.Integer, default=1)
    date = db.Column(db.DateTime)
    make_patches_time = db.Column(db.DateTime)
    import_type = db.Column(db.Text, default="drop")

    db.UniqueConstraint(projId,img_name)
    db.UniqueConstraint(projId,img_path)
    db.UniqueConstraint(projId,mask_path)

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class Labelnames(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    projId = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    label_id = db.Column(db.Integer)
    label_name = db.Column(db.Text)
    label_color = db.Column(db.Text)

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class Job(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    projId = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    imageId = db.Column(db.Integer, db.ForeignKey('image.id'), nullable=True)
    cmd = db.Column(db.Text)
    params = db.Column(db.Text)
    status = db.Column(db.Text)
    retval = db.Column(db.Text)
    start_date = db.Column(db.DateTime, server_default=db.func.now())
    end_date = db.Column(db.DateTime)

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class JobidBase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.Text)
    procout = db.Column(db.Text)

class Metrics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    projId = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    label_update_time = db.Column(db.DateTime)
    no_of_objects_labelled = db.Column(db.Integer, default=0)

    def as_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}




# Remove all queued and running jobs from the database
def clear_stale_jobs():
    jobs_deleted = Job.query.filter_by(status='QUEUE').delete()
    jobs_deleted += Job.query.filter_by(status='RUNNING').delete()
    return jobs_deleted


def set_job_status(job_id, status, retval = ""):
    if job_id:
        engine = sqlalchemy.create_engine(get_database_uri())
        if status == 'DONE':
            engine.connect().execute(f"update job set status= :status, retval = :retval, end_date= datetime('now') "
                                     f"where id={job_id}", status=status, retval = retval)
        else:
            engine.connect().execute(f"update job set status= :status, retval = :retval where id={job_id}", status=status, retval = retval)
        engine.dispose()
        jobs_logger.info(f'Job {job_id} set to status "{status}".')


# Output the project id from the database for a given name:
def get_project_id(project_name):
    return Project.query.filter_by(name=project_name).first().id


# Output the index of the latest trained ai
def get_latest_modelid(project_name):
    # pull the last training iteration from the database
    selected_proj = db.session.query(Project).filter_by(name=project_name).first()
    iteration = int(selected_proj.iteration)
    return iteration


def get_images(projectId):
    images = db.session.query(Image.id, Image.projId, Image.img_name, Image.mask_path, Image.mask_type,
                              Image.csv_path,Image.img_path, Image.height, Image.width, Image.date,
                              Image.make_patches_time, Image.nobjects). \
        filter(Image.projId == projectId).group_by(Image.id).all()

    return images

def get_objects_details(project_name):
    pytableLocation = f"./projects/{project_name}/patches_{project_name}.pytable"
    obj_count = 0
    percent_distrib = {}
    ann_obj_percent = 0
    if not os.path.isfile(pytableLocation):
        return obj_count, ann_obj_percent, percent_distrib
    with mutex:
        with tables.open_file(pytableLocation, mode='r') as hdf5_file:
            gt_label = hdf5_file.root.ground_truth_label[:]

    obj_count, ann_obj_percent, percent_distrib = get_annotations_percent(gt_label)

    return obj_count, ann_obj_percent, percent_distrib

def get_annotations_percent(ground_truth_array):
    ann_percentage = 0
    total_count = 0
    obj_ann_percent = {}
    counts = Counter(ground_truth_array)
    total_count = sum(counts.values())  # upgrade to python 3.10 and you can do counts.total()
    obj_ann_percent = {str(key): round(val / total_count * 100, 2) for key, val in counts.items()}

    if counts[-1] != total_count: #Check to verify if all data is 100% unlabelled
        # Check to verify if all data is 100% labelled
        ann_percentage = round(100 - obj_ann_percent["-1"],1) if "-1" in obj_ann_percent else 100
        
    #Eliminating -1 class to not appear in the final output at the frontend.
    obj_ann_percent.pop("-1",None)

    return total_count, ann_percentage, obj_ann_percent

#######################################################################################
##INsert without restlessAPI, used only from SWaggerUI
#######################################################################################
def insert_new_project(project_name, description,noLables):
    newProject = Project(name=project_name, description=description, no_of_label_type=int(noLables))
    db.session.add(newProject)
    db.session.commit()
    project = db.session.query(Project).filter_by(name=project_name).first()
    return project.id


#################################################################################
#Create Project and New Project Directory Structure
#################################################################################
def create_newproj_dir(project_name,noLabel,projId):
    # Check if the project folder exists
    if not os.path.isdir("projects"):
        os.mkdir("projects")

    if not os.path.isdir(os.path.join("projects", project_name)):
        # Create new project under root, add sub-folders
        os.mkdir(os.path.join("projects", project_name))

        os.mkdir(os.path.join("projects", project_name, "models"))
        os.mkdir(os.path.join("projects", project_name, "pred"))
        os.mkdir(os.path.join("projects", project_name, "mask"))
        os.mkdir(os.path.join("projects", project_name, "patches"))
        os.mkdir(os.path.join("projects", project_name, "temp"))
        os.mkdir(os.path.join("projects", project_name, "csv"))
        create_project_label(projId,noLabel)


# -- will be invoked for inserting new rows in the
# -- Labelnames table, label_name will be updated later.
def create_project_label(projectId, no_label_names):
    nolabel = int(no_label_names)
    color_map = ['rgb(228,26,28)', 'rgb(55,126,184)', 'rgb(77,175,74)', 'rgb(152,78,163)', 'rgb(255,127,0)',
                 'rgb(255,255,51)', 'rgb(166,86,40)', 'rgb(247,129,191)', 'rgb(153,153,153)']
    for cnt in range(nolabel):
        label_color = ""
        if len(color_map) >= nolabel:
            label_color = color_map[cnt]
        newLabel = Labelnames(projId=projectId, label_id=cnt, label_name=str(cnt), label_color=label_color)
        db.session.add(newLabel)
    db.session.commit()
    return True

def check_projectexists(project_name):
    # logging.info(f'************ the project name here is ---- {project_name}')
    proj = Project.query.filter_by(name=project_name).first()
    if proj is not None:
        raise ProcessingException(description=f'Project {project_name} already exists.', code=400)

    return False



def setup_flask_admin(app):
    admin = Admin(app, name='PS-admin', template_mode='bootstrap3')
    admin.add_view(ModelView(Project, db.session))
    admin.add_view(ModelView(Image, db.session))
    admin.add_view(ModelView(Labelnames, db.session))
    admin.add_view(ModelView(Job, db.session))
    admin.add_view(ModelView(JobidBase, db.session))
    admin.add_view(ModelView(Metrics, db.session))


def get_filtered_ids(idx, plot_by,filter_by,class_by,project_name):
    # current_app.logger.info(f"No of idx to be filtered {len(idx)}")
    pytableLocation = f"./projects/{project_name}/patches_{project_name}.pytable"
    time_init_mutex = perf_counter()
    with mutex:
        with tables.open_file(pytableLocation, mode='r') as hdf5_file:
            #Retireving all values and then filtering based on idx outside mutex
            rowCount = np.arange(int(hdf5_file.root.embed_x.shape[0]))
            gt_data = hdf5_file.root.ground_truth_label[:]
            pred_data = hdf5_file.root.prediction[:]
    time_end_mutex = perf_counter()
    current_app.logger.info(f"Time-(get_filtered_ids) for Mutex - {time_end_mutex-time_init_mutex}s")

    rc_idx = np.asarray(rowCount[idx])
    gt = gt_data[idx]
    pred = pred_data[idx]

    filter_idx = None
    if filter_by == int(FilterPlot.UNLABELED): #Unlabelled patch is always one with no ground truth.
        filter_idx = np.isin(gt, -1)
        if class_by != int(FilterPlot.ALL) and plot_by == int(FilterPlot.PREDICTION):
            filter_idx = filter_unlabelled_by_class(filter_idx,class_by,pred)
    elif filter_by == int(FilterPlot.LABELED):
        if class_by != int(FilterPlot.ALL):
            filter_idx = np.isin(gt, class_by)
        else:
            filter_idx = gt > -1
    elif filter_by == int(FilterPlot.DISCORDANT):#Discordant check is just gt != pred and hence not checkin for label or class.
        filter_idx = np.not_equal(pred,gt)
        dicordant = []
        for i, val in enumerate(filter_idx):
            if val:
                dicordant.append(gt[i] != -1)
            else:
                dicordant.append(False)
        filter_idx = dicordant
    elif filter_by == int(FilterPlot.ALL) and class_by != int(FilterPlot.ALL):
        filter_idx = np.isin(pred, class_by) if plot_by == int(FilterPlot.PREDICTION) else np.isin(gt, class_by)

    if filter_idx is not None:
        idx = rc_idx[filter_idx]
    # current_app.logger.info(f"Final no of returned idx : {len(idx)}")
    time_filter_end = perf_counter()
    current_app.logger.info(f"Time-(get_filtered_ids) for filtering - {time_filter_end-time_init_mutex}s")
    return idx

def filter_unlabelled_by_class(filterIds,class_val,pred_vals):
    filter_idx_class = []
    for i, x in enumerate(filterIds):
        if x:
            filter_idx_class.append(pred_vals[i] == class_val)
        else:
            filter_idx_class.append(False)
    return filter_idx_class