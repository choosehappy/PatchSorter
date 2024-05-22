# from multiprocessing import Lock

from flask import Blueprint
from flask_restx import Api

from patchsorter.api.image import api_ns_image
from patchsorter.api.patch.__init___ import api_ns_patch
from patchsorter.api.project import api_ns_project, api_ns_db
from patchsorter.api.image.search import api_ns_search

# mutex = Lock()

api_blueprint = Blueprint("api", __name__, url_prefix="/api")

api = Api(
    api_blueprint,
    title='Patch_Sorter API',
    version='1.0',
    description='A description',
    # All API metadatas
)

#
#Note : Incase there could be similar method names or routes for two different namespace , we need to specify the path so that it gets invoked.
api.add_namespace(api_ns_image)
api.add_namespace(api_ns_patch)
api.add_namespace(api_ns_project)
api.add_namespace(api_ns_db)
api.add_namespace(api_ns_search)

