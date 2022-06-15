import logging
from flask_restx import Namespace, Resource
from PS_api_patch_helper import *


api_ns_patch = Namespace('patch', description='Patch related operations')
jobs_logger = logging.getLogger('jobs')

##Api Defination
# - End point to retrieve the patch image for the mouse over event.
@api_ns_patch.route("/<project_name>/<patch_id>/image", endpoint="patch_image")
class PatchImage(Resource):
    @api_ns_patch.doc(params={'project_name': 'Which project?', 'patch_id': 'Patch Id?'})
    def get(self, project_name,patch_id):
        """     returns a Patch Image   """
        return get_patch_image(project_name, patch_id)

@api_ns_patch.route("/<project_name>/<patch_id>/context", endpoint="patch_context_image")
class PatchContextImage(Resource):
    @api_ns_patch.doc(params={'project_name': 'Which project?', 'patch_id': 'Patch Id?'})
    def get(self, project_name,patch_id):
        """     returns a Patch Context Image   """
        return get_patch_context_image(project_name, patch_id)

@api_ns_patch.route("/<project_name>/<patch_id>/mask", endpoint="patch_mask")
class PatchMask(Resource):
    @api_ns_patch.doc(params={'project_name': 'Which project?', 'patch_id': 'Patch Id?'})
    def get(self, project_name,patch_id):
        """     returns a Patch Mask Image   """
        return get_patch_mask(project_name, patch_id)

@api_ns_patch.route("/<project_name>/<patch_id>/patch_data", endpoint="patch_data")
class PatchData(Resource):
    @api_ns_patch.doc(params={'project_name': 'Which project?', 'patch_id': 'Patch Id or Ids seperated by a comma(,)?'})
    def get(self,project_name,patch_id):
        """     returns Patch Data   """
        return get_patch_data(project_name, patch_id)

    @api_ns_patch.doc(params={'project_name': 'Which project?', 'patch_id': 'Patch Id or Ids seperated by a comma(,)?','gt': 'GroundTruth = 0/1/2'})
    def put(self,project_name,patch_id):
        """     Updates Patch Data (GroundTruth)   """
        return update_ground_truth(project_name, patch_id)

@api_ns_patch.route("/<project_name>/patch_by_polygon", endpoint="patches_by_polygon")
class PatchByPolygon(Resource):
    @api_ns_patch.doc(params={'project_name': 'Which project?', 'polystring': 'd3 string for lasso'})
    def get(self,project_name):
        """     returns Patch Data   """
        polygonstring = request.args.get('polystring', None)
        plot_by = int(request.args.get('plot_by', 1));
        filter_by = int(request.args.get('filter_by', -1));
        class_by = int(request.args.get('class_by', -1));
        return patch_by_polygon(project_name,polygonstring,plot_by,filter_by,class_by)

@api_ns_patch.route("/<project_name>/patch_page", endpoint="patch_by_page")
class PatchByPage(Resource):
    @api_ns_patch.doc(params={'project_name': 'Which project?', 'pageNo': '1', 'embeddingKey':'Key','pageLimit':'10/50/100'})
    def get(self,project_name):
        """     returns Patch Data by Page  """
        pageNo = request.args.get('pageNo', None)
        embedKey = request.args.get('embeddingKey', None)
        pageLimit = int(request.args.get('pageLimit', 50))
        return patch_by_page(project_name,embedKey,pageNo,pageLimit)

@api_ns_patch.route("/<string:project_name>/closest_patch/<int:image_id>/<int:X>/<int:Y>", endpoint="closest_patch")
class ClosestPatch(Resource):
    @api_ns_patch.doc(params={'project_name': 'Which project?', 'image_id': 'Which image?', 'X': 'X query coordinate', 'Y': 'Y query coordinate'})
    def get(self,project_name, image_id, X, Y):
        return closeset_patch(project_name, image_id, X, Y)
