import json
import numpy as np

from flask_restx import Namespace, Resource
from sqlalchemy.exc import OperationalError
from flask import jsonify, request, make_response
from PS_db import Project, db
from PS_db import SearchCache, check_projectexists, create_newproj_dir, insert_new_project
from PS_config import config
from PS_api_project_helper import getconfig, make_patches,train_dl, make_embed, \
    ranged_embed, update_label_names,make_searchdb, get_project_status, \
    get_points_on_grid, get_job_status

api_ns_project = Namespace('project', description='Project related operations')


##Api Defination
@api_ns_project.route('/config')
class ProjectConfig(Resource):
    @api_ns_project.doc()
    def get(self):
        return getconfig()


@api_ns_project.route("/<string:project_name>/make_patches", endpoint='make_patches')
class Patches(Resource):
    @api_ns_project.doc(params={'project_name': 'Which project?'})
    def get(self, project_name):
        """  Makes Patches for the Project   """
        return make_patches(project_name)


@api_ns_project.route("/<string:project_name>/train_dl", endpoint='train_dl')
class TrainDl(Resource):
    @api_ns_project.doc(params={'project_name': 'Which project?'})
    def get(self, project_name):
        """  Training Deep Learning Model for the Project   """
        return train_dl(project_name)

@api_ns_project.route("/<string:project_name>/embed", endpoint='embed')
class Embed(Resource):
    @api_ns_project.doc(
        params={'project_name': 'Which project?'})
    def get(self, project_name):
        """  Makes Embeddings for the Project   """
        return make_embed(project_name)

# @SearchCache.cached(query_string=True)
@api_ns_project.route("/<string:project_name>/view_embed", endpoint='view_embed')
class ViewEmbed(Resource):
    @api_ns_project.doc(
        params={'project_name': 'Which project?','maxpoints': '0'})
    def get(self, project_name):
        """  View Embeddings for the Project   """
        proj = db.session.query(Project).filter_by(name=project_name).first()
        if proj is None:
            return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)

        xmin = round(request.args.get('xmin', default=proj.xmin, type=float),2)
        xmax = round(request.args.get('xmax', default=proj.xmax, type=float),2)
        ymin = round(request.args.get('ymin', default=proj.ymin, type=float),2)
        ymax = round(request.args.get('ymax', default=proj.ymax, type=float),2)
        plot_by = int(request.args.get('plot_by', 1));
        filter_by = int(request.args.get('filter_by', -1));
        class_by = int(request.args.get('class_by', -1));
        maxpoints = request.args.get('maxpoints',
                                     default=int(config.get('embed',
                                                            'maxpoints', fallback=5000)),type=int)
        if proj.embed_iteration == -2:
            return make_response(jsonify(error=f"For Graphs- 1.Embed or 2.Train DL and Embed for {project_name}."), 400)

        totalres, providedres, embedding, timing = ranged_embed(project_name, xmin, ymin, xmax, ymax, plot_by,
                                                                filter_by, class_by, maxpoints)

        return jsonify(success=True, totalres=totalres, providedres=providedres, embedding=embedding, xmin=xmin,
                       xmax=xmax, ymin=ymin, ymax=ymax,timing=timing)


@api_ns_project.route("/<string:project_name>/searchdb", endpoint='searchdb')
class SearchDb(Resource):
    @api_ns_project.doc(params={'project_name': 'Which project?'})
    def get(self, project_name):
        """ Create searchtree pkl file on the filesystem """
        return make_searchdb(project_name)


@api_ns_project.route('/<string:project_name>/labelnames', endpoint='label_names', doc=False)
class Labels(Resource):
    @api_ns_project.doc(params={'project_name': 'Which project?'})
    def put(self, project_name):
        label_list = json.loads(request.args.get("labels"))
        return update_label_names(project_name, label_list)


@api_ns_project.route('/<string:project_name>/project_status', endpoint='project_status')
class ProjectStatus(Resource):
    @api_ns_project.doc(params={'project_name': 'Which project?'})
    def get(self, project_name):
        return get_project_status(project_name)

    @api_ns_project.doc(
        params={'project_name': 'Which project?',
                'description': 'description',
                'no_of_label_type': 'no_of_label_type'})
    def post(self, project_name):
        description = request.args.get('description')
        no_label_types = request.args.get('no_of_label_type')
        if not check_projectexists(project_name):
            proj_id = insert_new_project(project_name, description, no_label_types)
            create_newproj_dir(project_name, no_label_types, proj_id)
            return make_response(jsonify(success=True), 204)

        return make_response(jsonify(error="Project Exists."), 400)


@api_ns_project.route('/job_stats/<string:job_id>')
class JobStats(Resource):
    @api_ns_project.doc(params={'job_id': 'Which job?'})
    def get(self, job_id):
        return get_job_status(job_id)


@api_ns_project.route('/<string:project_name>/points_on_grid', endpoint='points_on_grid')
class PointsOnGrid(Resource):
    @api_ns_project.doc(
        params={'project_name': 'Which project?',
                'xmin': 'xmin',
                'xmax': 'xmax',
                'ymin': 'ymin',
                'ymax': 'ymax'})
    def get(self, project_name):
        xmin = float(request.args.get('xmin', np.finfo(np.float).min))
        xmax = float(request.args.get('xmax', np.finfo(np.float).max))
        ymin = float(request.args.get('ymin', np.finfo(np.float).min))
        ymax = float(request.args.get('ymax', np.finfo(np.float).max))
        plot_by = int(request.args.get('plot_by', 1));
        filter_by = int(request.args.get('filter_by', -1));
        class_by = int(request.args.get('class_by', -1));
        return get_points_on_grid(project_name, xmin, xmax, ymin, ymax,plot_by,filter_by,class_by)



api_ns_db = Namespace('db', description='DB  related operations')


def rundbquery(query):
    try:
        result = db.session.execute(query)
        if result is None:
            return make_response(jsonify(error="Query has no records."), 400)
        results = [list(row) for row in result]
        response = make_response(jsonify(result=results), 200)
    except OperationalError:
        return make_response(jsonify(error="Table doesn't exist."), 404)
    return response

##Api Definition
@api_ns_db.route('/jobinfo', endpoint="jobinfo")
class JobInfo(Resource):
    @api_ns_db.doc(params={'job_id': 'Which Job?', "line_number": "From which line?"})
    def get(self):
        job_id = request.args.get('job_id', None)
        if not job_id:
            return make_response(jsonify(error="jobid not specified"), 400)

        line_number = int(request.args.get('line_number', 0))
        query = f"SELECT * FROM jobid_{job_id} WHERE id >={line_number}"
        return rundbquery(query)


@api_ns_db.route('/maxjobid', endpoint="maxjobid")
class MaxJobInfo(Resource):
    @api_ns_db.doc(params={'job_id': 'Which Job?'})
    def get(self):
        job_id = request.args.get('job_id', None)
        if not job_id:
            return make_response(jsonify(error="jobid not specified"), 400)

        query = f"SELECT ifnull(max(id), 0) FROM jobid_{job_id}"
        return rundbquery(query)
