import cv2
import PIL.Image

import os
import glob
import sqlalchemy
import json
import sys
import secrets
from datetime import datetime
from distutils.util import strtobool

from flask import current_app, request, make_response
from flask import send_from_directory, jsonify

from PS_db import Image, Project, db
from PS_pool import update_completed_job_status, pool_get_image
from PS_config import get_database_uri, config

# ------------
# @api_image_old.route("/api/<project_name>/image/<image_name>", methods=["GET"])
def get_image(project_name,image_id):
    current_app.logger.info(f"Outputting file id: {image_id}")
    proj = Project.query.filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)

    img = db.session.query(Image).filter_by(projId = proj.id,id=image_id).first()
    if img:
        basepath, filename = os.path.split(img.img_path)
        return send_from_directory(basepath, filename)
    else:
        response = make_response(jsonify(error=f"Image id {image_id} doesn't exist"), 400)
        response.headers["Content-type"] = "application/json"
        return response

def get_imagelist(project_name,pageNo,pageLimit):
    proj = Project.query.filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)

    # images = db.session.query(Image.id, Image.projId, Image.img_name, Image.mask_path, Image.csv_path, Image.img_path,
    #                           Image.height,Image.width, Image.date, Image.make_patches_time, Image.nobjects). \
    #                           filter(Image.projId == proj.id).order_by(Image.img_name.asc()).paginate(page=pageNo,per_page=pageLimit)
    images = db.session.query(Image.id, Image.projId, Image.img_name,Image.img_path). \
                              filter(Image.projId == proj.id).order_by(Image.id.asc()).paginate(page=pageNo,per_page=pageLimit)
    ###
    # Since SqlAlchemy object is not serializable a direct jsonify does not work hence making a seperate oject.
    ####
    imgList = [{'image_id':img.id,'image_name':img.img_name,'image_path':img.img_path} for img in images.items]

    return make_response(jsonify(images=imgList), 200)


# - End point to retrieve the thumbnail image for the uploaded images.
# @api_image.route("/api/<project_name>/image/<image_name>/thumbnail", methods=["GET"])
def get_image_thumb(project_name, image_name):
    width = request.form.get('width', 250)
    path = request.args.get('image_path')
    # img = cv2.imread(f"./projects/{project_name}/{image_name}")
    img = cv2.imread(path)

    height = int(img.shape[0] * width / img.shape[1])
    dim = (width, height)
    img = cv2.resize(img, dim)

    success, img_encoded = cv2.imencode('.png', img)

    response = make_response(img_encoded.tobytes())
    response.headers['Content-Type'] = 'image/png'
    response.headers['Content-Disposition'] = f'inline; filename = "{image_name.replace(".png", "_thumb.png")}"'
    return response

# @api_image.route("/api/<project_name>/image/<image_name>/mask", methods=["POST"])
def upload_mask(project_name, image_path=None,mask_path=None):
    proj = Project.query.filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)
    # TODO: need to handle *REST* route
    basepath, filename = os.path.split(mask_path)
    imgname = filename.replace("_mask","")  # this allows for accepting both \mask\train_1.png as well as train_1_mask.png
    if image_path is None:
        mask_fold = config.get('image_details', 'mask_folder', fallback='mask')
        if mask_fold in basepath:
            path, maskfolder = os.path.split(basepath)
            image_path = os.path.join(path, imgname)
        else:
            image_path = mask_path.replace("_mask","") #Needed to query for Image based on path, will help if two images of the same name are present in different paths.
    img = db.session.query(Image).filter_by(projId = proj.id, img_name=imgname,img_path=image_path).first()
    # Error Handling : if img is none, need to throw an error visible to the user
    if not img:
        current_app.logger.warn(f"ERROR:Mask not uploaded,img for {imgname} doesn't exists in DB")
        return make_response(jsonify(error=f"img for {imgname} doesn't exist in DB"), 404)
    img.mask_path = mask_path
    db.session.commit()
    return make_response(jsonify(success=True), 201)

# @api_image_old.route("/api/<project_name>/csv", methods=["POST"])
def upload_csv(project_name,image_path=None,csv_file_path=None):
    proj = Project.query.filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)
    current_app.logger.info(f'Project = {str(proj.id)}')
    # TODO: need to handle REST route
    basepath, filename = os.path.split(csv_file_path)
    imgname = filename.replace(".csv", ".png")  # assumes train_1.png --- > train_1.csv
    if image_path == None:
        csv_fold = config.get('image_details', 'csv_folder', fallback='csv')
        if csv_fold in basepath:
            path, csvfolder = os.path.split(basepath)
            image_path = os.path.join(path, imgname)
        else:
            image_path = csv_file_path.replace(".csv", ".png")
    img = db.session.query(Image).filter_by(projId = proj.id, img_name=imgname,img_path=image_path).first()
    # TODO: if img is none, need to throw an error visible to the user
    img.csv_path = csv_file_path
    db.session.commit()
    return make_response(jsonify(success=True), 201)

# -- Endpoint to upload an image either via drag drop or upload a single image or upload a folder
# @api_image_old.route("/api/<project_name>/image", methods=["POST"])
def upload_image(project_name, abs_file_path=None):
    current_app.logger.info(f'Uploading image for project {project_name} :')
    # ---- check project exists first!
    proj = Project.query.filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)
    current_app.logger.info(f'Project = {str(proj.id)}')

    if not abs_file_path:  # assume request
        file = request.files.get('file')
        filename = file.filename
        dest = f".{os.path.sep}projects{os.path.sep}{project_name}{os.path.sep}{filename}"
        import_type ="drop"
        # Check if the file name has been used before
        # TODO:Currently an error is returned but no message shown to the user on the error.
        if os.path.isfile(dest):
            return make_response(jsonify(error="file already exists"), 400)
        # TODO: need to check if mask and csv already exists and show a user
        # Code changed to resolve Issue #677
        ## Start
        if "mask" in filename:  # then try to match the masks
            # dest = f"./projects/{project_name}/mask/{filename}"
            dest = f".{os.path.sep}projects{os.path.sep}{project_name}{os.path.sep}mask{os.path.sep}{filename}"
            upload_mask(project_name,None,dest)
            file.save(dest)
            return make_response(jsonify(success=True), 201)
        if filename.lower().endswith('csv'):
            # dest = f"./projects/{project_name}/csv/{filename}"
            dest = f".{os.path.sep}projects{os.path.sep}{project_name}{os.path.sep}csv{os.path.sep}{filename}"
            upload_csv(project_name,None,dest)
            file.save(dest)
            return make_response(jsonify(success=True), 201)
        ## End
        # if it's not a png image
        filebase, fileext = os.path.splitext(filename)

        file.save(dest)

        if fileext != ".png":
            current_app.logger.info('Resaving as png:')
            # file.save(filename) #temp save
            dest_png = f".{os.path.sep}projects{os.path.sep}{project_name}{os.path.sep}{filebase}.png"
            current_app.logger.info(dest_png)
            current_app.logger.info("saving...")
            im = PIL.Image.open(dest)
            im.thumbnail(im.size)
            current_app.logger.info(im.size)
            im.save(dest_png, 'png', quality=100)
            os.remove(dest)
            dest = dest_png

        # Get image dimension
        im = PIL.Image.open(dest)
    else:
        import_type = "upload"
        basepath, filename = os.path.split(abs_file_path)
        filebase, fileext = os.path.splitext(filename)
        dest = abs_file_path
        # Get image dimension
        im = PIL.Image.open(dest)

    current_app.logger.info(f'Destination = {dest}')

    # Save the new image information to database
    newImage = Image(img_name=f"{filebase}.png", img_path=dest, mask_path=None, csv_path=None, projId=proj.id,
                     width=im.size[0], height=im.size[1], import_type=import_type, date=datetime.utcnow())

    db.session.add(newImage)
    db.session.commit()
    # Issue #677 - Changed the return and removed the image=newImage.as_dict() as it does not seem to be needed.
    # Original return was jsonify(success=True, image=newImage.as_dict()), 201
    response = make_response(jsonify('Success'), 201)
    response.headers["Content-type"] = "application/json"
    return response
    # return jsonify(success=True), 201

def upload_image_folder(project_name):
    abs_dir_path = request.args.get('folder_path')
    if os.path.exists(abs_dir_path) and os.path.isfile(abs_dir_path) and abs_dir_path.endswith(".csv"):
        upload_from_list(project_name,abs_dir_path)
    if os.path.exists(abs_dir_path) and os.path.isdir(abs_dir_path):
        for filename in glob.glob(abs_dir_path + os.sep + "**", recursive=True):
            if not filename.lower().endswith((
                    '.png')):  # can eeasily extend to other datatypes here #, '.jpg', '.jpeg', '.tiff', '.bmp', '.gif')):  #--- need to upload images first
                continue
            if not "mask" in os.path.basename(filename):
                upload_image(project_name, filename)

        for filename in glob.glob(abs_dir_path + os.sep + "**", recursive=True):
            if not filename.lower().endswith(('.png')):  # can easily extend to other datatypes here # , '.jpg', '.jpeg', '.tiff', '.bmp', '.gif')):
                continue
            if "mask" in os.path.basename(filename):  # then try to match the masks
                upload_mask(project_name,None,filename)

        for filename in glob.glob(abs_dir_path + os.sep + "**", recursive=True):  # lastly any CSV
            if filename.lower().endswith('.csv'):
                upload_csv(project_name,None,filename)

            # later we might keep a check if one image upload fails we could send a error message to the user.
    response = make_response(jsonify('Success'), 201)
    response.headers["Content-type"] = "application/json"
    return response
    # return jsonify(success=True), 201


def get_mask(project_name, image_id,image_name):
    current_app.logger.info(f"Outputting file {image_name}")
    proj = Project.query.filter_by(name=project_name).first()
    if proj is None:
        return make_response(jsonify(error=f"project {project_name} doesn't exist"), 400)
    # Image is filtered by project ID
    img = db.session.query(Image).filter_by(projId = proj.id,id=image_id).first()
    if img.mask_path:
        basepath, filename = os.path.split(img.mask_path)
        return send_from_directory(basepath, filename)
    else:
        response = make_response(jsonify(error=f"Mask for Image '{image_name}' doesn't exist, Please upload a Mask."), 400)
        response.headers["Content-type"] = "application/json"
        return response


def delete_output_image(project_name, image_id,image_name, type = None):

    overlay = strtobool(request.args.get('overlay', "True", type=str))
    outdir = f"./projects/{project_name}/"
    full_fname= f"{outdir}/{type}/overlay/{image_name}" if overlay else f"{outdir}/{type}/{image_name}"
    if os.path.isfile(full_fname): os.remove(full_fname)
    response = make_response(jsonify('Deleted'), 200)
    return response


def get_output_image(project_name, image_id,image_name, output_type = None):
    current_app.logger.info(f'Getting superpixel for project {project_name} and image {image_name}')

    project = db.session.query(Project).filter_by(name=project_name).first()
    if project is None:
        current_app.logger.warn(f'Unable to find {project_name} in database. Returning HTML response code 400.')
        return make_response(jsonify(error=f"Project {project_name} does not exist"), 400)
    if project.embed_iteration <= -2 and output_type == "pred" :
        current_app.logger.warn(f'Project {project_name} needs to be embedded. Returning HTML response code 400.')
        return make_response(jsonify(error=f"Project {project_name} not embedded. Please Make Patches and Embed Patches."), 400)

    overlay = strtobool(request.args.get('overlay', "True", type=str))

    if not output_type: #parse REST call, otherwise use explicitly set type
        output_type = request.path.split("/")[-1]


    csvfileName = f"./projects/{project_name}/temp/output_details_{secrets.token_urlsafe(10)}.csv";
    with open(csvfileName, "w") as f:
        image = db.session.query(Image.id, Image.img_name, Image.mask_path, Image.csv_path, Image.img_path). \
            filter(Image.projId == project.id).filter(Image.id == image_id).first()
        mask_path = image.mask_path if image.mask_path else ''
        csv_path = image.csv_path if image.csv_path else ''

        f.write(f"{image.id},{image.img_path},{mask_path},{csv_path}\n")

    pytablefile = f"./projects/{project_name}/patches_{project_name}.pytable";

    outdir = f"./projects/{project_name}/"
    imgoutput_script_name = config.get('image_output', 'imgoutput_script_name',
                                      fallback='./approaches/image_output/make_img_outputs.py')
    # get the command, note its easier to always generate overlay even if it isn't requested
    full_command = [sys.executable,
                    f"{imgoutput_script_name}", f"-t{output_type}", f"-o{outdir}","--overlay",
                    "--overlayids",f"{csvfileName}",f"{pytablefile}"]


    full_fname= f"{outdir}/{output_type}/overlay/{image_name}" if overlay else f"{outdir}/{output_type}/{image_name}"


    current_app.logger.info(
        f'We are running outputgen to generate output for IMAGE {image_name} in PROJECT {project_name} ')
    current_app.logger.info(f'output command = {full_command}')
    command_name = "make_output"

    return pool_get_image(project_name, command_name, full_command, full_fname,
                          imageid=image.id, callback=make_output_callback)

def make_output_callback(result):
    # update the job status in the database:
    update_completed_job_status(result)
    retval, jobid = result
    engine = sqlalchemy.create_engine(get_database_uri())
    dbretval = engine.connect().execute(f"select procout from jobid_{jobid} where procout like 'RETVAL:%'").first()
    if dbretval is None:
        # no retval, indicating make_output didn't get to the end, leave everything as is
        engine.dispose()
        return
    else:
        retvaldict = json.loads(dbretval[0].replace("RETVAL: ", ""))
        os.remove(retvaldict['csvfile'])
        engine.dispose()

def get_output_overlayids(project_name, image_id,image_name, output_type,overlay_type):
    current_app.logger.info(f'Getting overlay_ids {project_name} and image {image_name}')

    project = db.session.query(Project).filter_by(name=project_name).first()
    if project is None:
        current_app.logger.warn(f'Unable to find {project_name} in database. Returning HTML response code 400.')
        return make_response(jsonify(error=f"Project {project_name} does not exist"), 400)

    outdir = f"./projects/{project_name}/"

    if 'w_ids' in overlay_type:
        filebase, fileext = os.path.splitext(image_name)
        file_name = filebase+'_overlayid.png'
        image_filename = f"{outdir}/{output_type}/overlay/{file_name}"
    else:
        image_filename = f"{outdir}/{output_type}/overlay/{image_name}"

    if not os.path.isfile(image_filename):
        return make_response(jsonify(error=f"Project output has not been generated does not exist"), 400)
    else:
        # This image exists and the job is done; output it to the frontend:
        folder, filename = os.path.split(image_filename)
        return send_from_directory(folder, filename)




# Method defined to upload a list of files , pattern would be [image_name.png,image_name_mask.png,image_name.csv]
def upload_from_list(project_name,abs_dir_path):
    for line in open(abs_dir_path, 'r'):
        current_app.logger.info(line.strip())
        sline = line.strip().split(",")
        image_path = sline[0]
        upload_image(project_name, image_path)
        if len(sline) > 1 and len(sline[1]) > 0:
            image_maskpath = sline[1]
            upload_mask(project_name,image_path,image_maskpath)
        if len(sline) > 2 and len(sline[2]) > 0:
            image_csv_path = sline[2]
            upload_csv(project_name,image_path,image_csv_path)
        current_app.logger.info(f"Progress: Working on image {image_path}!")
    return jsonify(success=True), 201


