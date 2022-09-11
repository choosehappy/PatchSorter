import os
import tables

from collections import Counter

from flask import jsonify
from flask import current_app, request
from flask_restx import Resource, Api,Namespace
from werkzeug.datastructures import FileStorage

from PS_db import Image, Project, db
from PS_api_image_helper import get_image_thumb, get_image, upload_image, upload_image_folder, get_mask, \
    get_output_image,get_imagelist,delete_output_image, get_output_overlayids
# from multiprocessing import Lock
from PS_utils import mutex

# mutex = Lock()

#################################################################################
api_ns_image = Namespace('image', description='Image related operations')


## Used for Swagger UI to be able to upload an image.
upload_parser = api_ns_image.parser()
upload_parser.add_argument('file', location='files',type=FileStorage, required=True)

@api_ns_image.route('/<string:project_name>/image', endpoint="image")
# @api_image.route('/<string:project_name>/image', endpoint="upload_image")
class Images(Resource):
    @api_ns_image.doc(params={'project_name': 'Which project?','image_id': 'Id of Image'})
    def get(self,project_name):
        """     returns an Image/ImageList   """
        image_id = request.args.get('image_id',None)
        if image_id:
            return get_image(project_name, image_id)
        else:
            pageNo = request.args.get('pageNo', default=0, type=int)
            pageLimit = request.args.get('pageLimit', default=16, type=int)
            return get_imagelist(project_name,pageNo,pageLimit)
    @api_ns_image.doc(params={'project_name': 'Which project?', 'file': 'Path for the image file?'})
    @api_ns_image.expect(upload_parser, validate=True)
    def post(self,project_name,abs_file_path=None):
        """ Uploads and Image """
        return upload_image(project_name, abs_file_path)

#################################################################################

@api_ns_image.route('/<string:project_name>/image/<string:image_name>/thumbnail',endpoint="get_image_thumb")
@api_ns_image.doc(params={'project_name': 'Which project?', 'image_name': 'Which image?', 'image_path':'path for image'})
class ImageThumbnail(Resource):
    def get(self, project_name, image_name):
        """     returns an Image Thumbnail   """
        return get_image_thumb(project_name, image_name)
#################################################################################


# - Endpoint used to upload images from a folder path, using os package right now, and
# assuming the folder import will have images on root naming convention "images.png"
# will have a folder named masks with mask images naming convention "images_mask.png"
# and csv for respective images naming convention "images_csv.png"
@api_ns_image.route("/<string:project_name>/image_folder", endpoint="upload_image_folder")
@api_ns_image.doc(params={'project_name': 'Which project?', 'folder_path': 'path for folder to be uploaded'})
class ImageFolder(Resource):
    def post(self,project_name):
        """     Uploads all Images/Masks/Csv from the folder  or a list with paths  """
        return upload_image_folder(project_name)



@api_ns_image.route("/<string:project_name>/image_mask", endpoint="mask")
@api_ns_image.doc(params={'project_name': 'Which project?', 'image_id': 'Which Image id?','image_name': 'Which Image ?'})
class ImageMask(Resource):
    def get(self, project_name):
        """     Returns the image mask   """
        image_id = request.args.get('image_id')
        image_name = request.args.get('image_name')
        return get_mask(project_name,image_id,image_name)



##Changed the route to hold the value of type - for the type of output (gt/pred)
@api_ns_image.route("/<string:project_name>/image_output/<string:image_name>", endpoint="get_output_image_pred")
@api_ns_image.route("/<string:project_name>/image_output/<string:image_name>", endpoint="get_output_image_gt")
class ImageOutput(Resource):
    @api_ns_image.doc(params={'project_name': 'Which project?', 'image_id': 'Which Image id?','image_name':'Which Image?',
                              'output_type' : 'What output [type=pred or gt]'})
    def get(self,project_name,image_name):
        image_id = request.args.get('image_id')
        # image_name = request.get('image_name')
        overlay_type = request.args.get('overlay_type')
        output_type = request.args.get('output_type')
        if 'na' in overlay_type:
            return get_output_image(project_name, image_id, image_name, output_type)
        else:
            return get_output_overlayids(project_name, image_id, image_name, output_type,overlay_type)
    def delete(self,project_name,image_name):
        image_id = request.args.get('image_id')
        # image_name = request.get('image_name')
        output_type = request.args.get('output_type')
        return delete_output_image(project_name, image_id, image_name, output_type)




# - End point to delete images currently not in use.
# @api_image_old.route('/api/<project_name>/image/<image_name>',
#            methods=["DELETE"])  # below should be done in a post-processing call
def delete_image(project_name, image_name):
    proj = Project.query.filter_by(name=project_name).first()
    if proj is None:
        return jsonify(error=f"project {project_name} doesn't exist"), 400

    # Remove the image from database
    selected_image = db.session.query(Image).filter_by(projId=proj.id, img_name=image_name).first()
    if selected_image:
        db.session.delete(selected_image)
        db.session.commit()
    # Since some Images just have a upload path and not physical copy.
    # will check if selected_image.import_type is 'drop' then delete the physical copy of image.
    if os.path.exists(selected_image.import_type) == 'drop':
        os.remove(selected_image.path)
    return jsonify(success=True), 204

# - End point to retrieve image stats currently not in use
# @api_image_old.route("/api/<project_name>/image/<image_name>/stats", methods=["GET"])
def get_image_stats(project_name, image_name):
    project = db.session.query(Project).filter_by(name=project_name).first()
    if project is None:
        current_app.logger.warn(f'Unable to find {project_name} in database. Returning HTML response code 400.')
        return jsonify(error=f"Project {project_name} does not exist"), 400

    image = db.session.query(Image.id, Image.img_name, Image.mask_path, Image.csv_path, Image.img_path). \
        filter(Image.projId == project.id).filter(Image.img_name == image_name).first()

    pytableLocation = f"./projects/{project_name}/patches_{project_name}.pytable";
    with mutex:
        with tables.open_file(pytableLocation, mode='r') as hdf5_file:
            # Added rowCount to use it for Patch_id.
            idx = hdf5_file.root.imgID[:] == image.id
            nobj = sum(idx)
            idx_anno = hdf5_file.root.ground_truth_label[idx] != -1
            nobjanno = sum(idx_anno)
            predcounts = Counter(hdf5_file.root.prediction[idx].tolist())
            gtcounts = Counter(hdf5_file.root.ground_truth_label[idx][idx_anno].tolist())

    return jsonify(success=True, imageid=image.id,nobj=int(nobj),nobjanno=int(nobjanno),
                   predcounts=predcounts,gtcounts=gtcounts)