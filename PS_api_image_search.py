import uuid
import json
import os
import os.path
import subprocess
import sys
import re

from flask import current_app, jsonify, request, make_response
from flask_restx import Namespace, Resource

from PS_config import config
from PS_db import Project, db
from PS_db import get_latest_modelid
from PS_searchtree_store import SearchResultStore

api_ns_search = Namespace('search', description='Project related operations')


@api_ns_search.route("/<string:project_name>/search/upload_image_search", endpoint='upload_image_search')
class UploadSearchImage(Resource):
    @api_ns_search.doc(
        params={'project_name': 'Which project?'})
    def post(self, project_name):
        """  View Embeddings for the Project   """
        proj = db.session.query(Project).filter_by(name=project_name).first()
        if proj is None:
            return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)

        file = request.files['file']
        # if user does not select file
        # submit a empty part without filename
        if file.filename == '' or not file.filename.endswith(
                "png"):  # assume only png, should be expanded to include reasonable formats, jpg, tif, others?
            return jsonify("error")  # put reasonable error message here

        image_fname = os.path.join('projects', project_name, "image_search", file.filename)
        dir = os.path.dirname(image_fname)
        if not os.path.exists(dir):
            os.mkdir(dir)

        file.save(image_fname)

        return jsonify(success=True, fname=file.filename)


@api_ns_search.route("/<string:project_name>/search/image_search", endpoint='image_search')
class ImageSearch(Resource):
    @api_ns_search.doc(
        params={'project_name': 'Which project?',
                'filename': 'What was the uploaded filename?',
                'approach': 'Which search approach to use?',
                'nneighbors': 'How many matches to be returned?',
                'max_threshold': 'Max threshold for positive result'})  # add modelid
    def post(self, project_name):
        proj = db.session.query(Project).filter_by(name=project_name).first()
        if proj is None:
            return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)

        file = request.files['file']
        filename = file.filename # request gives empty file object with filename '' if no file selected
        allowed_ext = ['.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif']
        basename, ext = os.path.splitext(filename)
        if filename == '' or os.path.splitext(filename)[1] not in allowed_ext:
            return make_response(jsonify(error=f"File uploaded is not correct."), 400)

        image_fname = os.path.join('projects', project_name, "image_search", filename)
        dir = os.path.dirname(image_fname)
        if not os.path.exists(dir):
            os.mkdir(dir)

        file.save(image_fname)
        try:
            max_threshold = int(request.form.get('max_threshold',
                                                 config.get('image_search', 'max_threshold', fallback=100)))
            nneighbors = int(request.form.get('nneighbors',
                                              config.get('image_search', 'nneighbors', fallback=100)))
        except ValueError:
            return make_response(jsonify(error="Threshold and Nneighbors have to be numbers"), 400)

        patch_size = config.getint('image_search', 'patchsize', fallback=32)
        model_name = f"./projects/{project_name}/models/{get_latest_modelid(project_name)}/"

        pytablefile = f"./projects/{project_name}/patches_{project_name}.pytable"
        if not os.path.isfile(pytablefile):
            return make_response(jsonify(error="pytable file does not exist, consider making patches first"), 400)

        # --- figure out which key
        approach_script_name = config.get('image_search', 'approach_options',
                                          fallback='embed:Embedding:./approaches/image_search/image_search_embed.py')
        approaches = approach_script_name.splitlines()  # this part should really be done by converting the list to a dict, and then accesing tuple by key
        keys = [a.split(":")[0] for a in approaches]
        approach = request.form.get('approach',
                                    default=config.get('image_search', 'approach_default', fallback="embed"))
        try:
            if approach not in keys:
                current_app.logger.info(f'Approach {approach} is not found in config.ini using default approach')
                approach = config.get('image_search', 'approach_default', fallback="embed")
            idx = keys.index(approach)  # issue failure here if not in list
        except ValueError:
            return make_response(jsonify(error="Error finding search patches approach"), 400)

        search_script_name = approaches[idx].split(":")[2]

        # get the command:
        full_command = [sys.executable, search_script_name, project_name, pytablefile, image_fname, model_name,
                        f"-p{patch_size}", f"-n{nneighbors}", f"-m{max_threshold}"]

        current_app.logger.info(f'Full command = {str(full_command)}')

        dbretval_result = subprocess.run(full_command, capture_output=True, text=True).stdout
        # The result comes with an escape character in the end [0m and hence compile it to remove it.
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        result = ansi_escape.sub('', dbretval_result)
        if 'RETVAL' in result:
            json_results = (result.split("RETVAL: ")[1]).strip()
            retvaldict = json.loads(json_results)

            hits = retvaldict['hits']
            if len(hits):
                embedkey = str(uuid.uuid4())
                SearchResultStore[embedkey] = hits
                print(f"embedKey is {embedkey} and count is {len(hits)}");
                return make_response(jsonify(embeddingCnt=len(hits), embeddingKey=embedkey), 200)
            else:
                return make_response(jsonify(error="No Patches found"), 400)
        else:
            return make_response(jsonify(error="System Error Occured"), 400)