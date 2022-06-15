from flask import render_template, Blueprint, request, current_app
from flask_sqlalchemy import SQLAlchemy

from PS_config import config
from PS_db import Image, Project, Job, get_latest_modelid, get_images

html = Blueprint("html", __name__, static_folder="static", template_folder="templates")
db = SQLAlchemy()
@html.route('/favicon.ico')
def favicon():
    return html.send_static_file("favicon.ico")


@html.route('/')
def index():
    projects = db.session.query(Project.name, Project.date, Project.iteration, Project.description, Project.id, Project.no_of_label_type,
                                Project.images,  db.func.count(db.func.distinct(Image.id)).label('nImages'),
                                db.func.ifnull(db.func.sum(db.func.distinct(Image.nobjects)), 0).label('nObjects'))  \
                                .outerjoin(Image, Image.projId == Project.id).group_by(Project.id).all()

    return render_template("index.html", projects=projects)

@html.route('/<project_name>', methods=['GET'])
@html.route('/<project_name>/view_embed', methods=['GET'])
def view_embed(project_name):
    project = Project.query.filter_by(name=project_name).first()
    if not project:
        return render_template("error.html")
    return render_template("embed.html", project=project)

@html.route('/<project_name>/view_embed/view_embed_main', methods=['GET'])
def view_embed_main(project_name):
    # project = Project.query.filter_by(name=project_name).first()
    #Modified the query to include the count of images to show on the front end.
    project = db.session.query(Project.id, Project.name, Project.description, Project.date, Project.make_patches_time,
                               Project.no_of_label_type, Project.iteration, Project.embed_iteration,
                                Project.images,  db.func.count(db.func.distinct(Image.id)).label('nImages'))  \
                                .outerjoin(Image, Image.projId == Project.id).filter(Project.name==project_name).group_by(Project.id).first()
    if not project:
        return render_template("error.html")
    else:
        return render_template("view_embed_main.js", project=project)

@html.route('/<project_name>/view_embed/view_embed_plot', methods=['GET'])
def view_embed_plot(project_name):
    project = Project.query.filter_by(name=project_name).first()
    context_patch_size = config.getint('frontend', 'context_patch_size', fallback=256)
    patch_size = config.getint('frontend', 'patchsize', fallback=32)
    if not project:
        return render_template("error.html")
    else:
        return render_template("view_embed_plot.js", project=project)

@html.route('/<project_name>/view_embed/view_embed_utils', methods=['GET'])
def view_embed_utils(project_name):
    project = Project.query.filter_by(name=project_name).first()
    if not project:
        return render_template("error.html")
    else:
        return render_template("view_embed_utils.js", project=project)

@html.route('/<project_name>/view_embed/view_patchgrid_plot', methods=['GET'])
def view_patchgrid_plot(project_name):
    project = Project.query.filter_by(name=project_name).first()
    context_patch_size = config.getint('frontend', 'context_patch_size', fallback=256)
    patch_size = config.getint('frontend', 'patchsize', fallback=32)
    if not project:
        return render_template("error.html")
    else:
        return render_template("view_patchgrid_plot.js", project=project, context_patch_size = context_patch_size, patch_size=patch_size)


@html.route('/<project_name>/images/images_main', methods=['GET'])
def images_main(project_name):
    # Get the image list for the project
    # project = Project.query.filter_by(name=project_name).first()
    # Modified the query to include the count of images to show on the front end.
    project = db.session.query(Project.id, Project.name, Project.description, Project.date, Project.make_patches_time,
                               Project.no_of_label_type, Project.iteration, Project.embed_iteration,
                                Project.images,  db.func.count(db.func.distinct(Image.id)).label('nImages'))  \
                                .outerjoin(Image, Image.projId == Project.id).filter(Project.name==project_name).group_by(Project.id).first()
    if not project:
        return render_template("error.html")
    else:
        return render_template("images_main.js", project=project)



@html.route('/<project_name>/images', methods=['GET'])
def view_images(project_name):
    # Get the image list for the project
    project = Project.query.filter_by(name=project_name).first()
    if not project:
        return render_template("error.html")

    return render_template("images.html", project=project)

##End point used for image output for Annotaions and Prediction.
@html.route('/<project_name>/image/<image_id>/gt', methods=['GET'], endpoint="get_output_image_gt")
@html.route('/<project_name>/image/<image_id>/pred', methods=['GET'], endpoint="get_output_image_pred")
@html.route('/<project_name>/image/<image_id>/image', methods=['GET'], endpoint="view_image")
@html.route('/<project_name>/image/<image_id>/mask', methods=['GET'], endpoint="view_mask")
def get_image_output(project_name,image_id):
    project = Project.query.filter_by(name=project_name).first()
    if not project:
        return render_template("error.html")
    img = db.session.query(Image).filter_by(projId = project.id,id=image_id).first()
    if not img:
        return render_template("error.html")
    type = request.path.split("/")[-1]
    if type=="pred" or type=="gt":
        html_template = "image_output.html"
    else:
        html_template = "image_view.html"
    return render_template(html_template, project=project, image_name=img.img_name, image_id=img.id, type=type)

@html.route('/help', methods=['GET'])
def view_help():
    return render_template("help.html")