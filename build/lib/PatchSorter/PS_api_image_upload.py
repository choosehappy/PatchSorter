import os
from enum import Enum
from flask import render_template, Blueprint, request, current_app
from PS_db import Project, Image, db, MaskTypeEnum
import hashlib
import PIL.Image
from datetime import datetime
import csv
import numpy as np
from thefuzz import fuzz
import skimage.measure
from sqlalchemy.exc import IntegrityError
from shutil import rmtree
from time import perf_counter

upload_modal = Blueprint("upload", __name__, static_folder="static", template_folder="templates")


@upload_modal.route('/upload/<string:project_name>/modal/', methods=['GET'])
def get_modal(project_name):
    """Return replacement contents for the modal dialog depending on the current upload step"""
    project = Project.query.filter_by(name=project_name).first()
    session_id = 1  # TODO: Generate a row for this upload session in the database and return the ID
    data = {'session_id': session_id, 'modal': render_template("image_upload_modal.html", project=project)}
    return data


@upload_modal.route('/upload/<project_name>/<session_id>/validate/', methods=['POST'])
def validate_paths(project_name, session_id):
    """At the beginning of the Review Data step, evaluate the file names/paths provided for feasibility"""
    t_review_start  = perf_counter()
    request_data = request.get_json()
    is_list = ('list' in request_data and len(request_data['list'])>0)
    if is_list:
        paths, errors = _get_list_paths(project_name, session_id, request_data['list'][0])
    else:
        paths, errors = _get_image_paths(request_data, session_id)
    
    # prepare the output
    data = {
        'paths': paths,
        'errors': errors,
        'list': is_list
    }

    # pass on this info
    for upload_type in ['image', 'mask', 'csv']:
        key = upload_type + '_is_folder'
        data[key] = request_data[key]
    t_review_end = perf_counter()
    print(f"Time taken to review these files is {t_review_end-t_review_start}")
    return data


# returns either None or a string containing an error message
def _invalid_extension_error(upload_type, filename):
    allowed_extensions = {
        'image': ['png', 'jpg', 'jpeg', 'bmp', 'tiff', 'tif'],
        'csv': ['csv']
    }
    allowed_extensions['mask'] = allowed_extensions['image']
    _, extension = os.path.splitext(filename)
    extension = extension[1:].lower()
    allowed = allowed_extensions[upload_type]
    if extension in allowed:
        return None
    else:
        return f'{upload_type} {os.path.basename(filename)} has invalid extension \'{extension}\' - the only allowed extensions are {allowed}.'


def _get_list_paths(project_name, session_id, list_filename):
    # current_app.logger.debug('Entered _get_list_paths')
    # current_app.logger.debug(f'session_id = {session_id}')
    # current_app.logger.debug(f'list_filename = {list_filename}')

    folder = _get_session_upload_subfolder(project_name, session_id, upload_type='list')
    list_path = os.path.join(folder, list_filename)

    output_paths = []
    error_count = 0

    try:
        with open(list_path) as csv_file:
            csv_reader = csv.reader(csv_file, delimiter=',')

            for row in csv_reader:

                cols = len(row)
                if cols == 0:
                    continue
            
                output_item = {
                    'status': 'READY TO IMPORT',
                    'from_dropzone': False
                }

                def _append_filename(upload_type, filename, output_item):
                    if os.path.isfile(filename):
                        if extension_error := _invalid_extension_error(upload_type, filename):
                            output_item['error'] = extension_error
                        else:
                            output_item[upload_type] = filename
                    else:
                        output_item['error'] = f'{upload_type} {filename} not found.'
                
                filename = row[0]
                upload_type = 'image'
                _append_filename(upload_type, filename, output_item)
                
                if cols > 1 and len(row[1]) > 0:
                    filename = row[1]
                    upload_type = 'mask'
                    _append_filename(upload_type, filename, output_item)

                    if cols > 2 and len(row[2]) > 0:
                        filename = row[2]
                        upload_type = 'csv'
                        _append_filename(upload_type, filename, output_item)

                if 'error' in output_item:
                    error_count += 1
                    output_item['status'] = 'ERROR: INVALID FILENAME'

                output_paths.append(output_item)

    except:
        return f'Unable to load csv file {list_filename}', 400

    return output_paths, error_count


def _get_image_paths(upload_paths, session_id):
    """Given the data provided in a validate_paths AJAX call, return a list of Image paths"""

    def _get_files_in_dir(directory, upload_type):
        all_files = list(map(lambda filename: os.path.abspath(os.path.join(directory, filename)), next(os.walk(directory))[2]))
        only_valid_extensions = [filename for filename in all_files if not _invalid_extension_error(upload_type, filename)]
        return only_valid_extensions

    upload_types = ['image', 'mask', 'csv']
    input_filenames = {}
    available_filenames = {}

    output_data = []
    error_count = 0

    for upload_type in upload_types:

        input_filenames[upload_type] = upload_paths[upload_type]

        # if the user selected a folder, load the files from that folder
        is_folder_suffix = '_is_folder'
        if (upload_paths[upload_type + is_folder_suffix]) and len(input_filenames[upload_type]) > 0:
            available_filenames[upload_type] = []
            input_dir = input_filenames[upload_type]
            try:
                input_filenames[upload_type] = _get_files_in_dir(input_dir, upload_type)
            except:
                # no files
                output_item = {
                    upload_type: input_dir,
                    'status': 'ERROR: BAD DIR',
                    'error': f'No files found in folder {input_dir}'
                }
                output_data.append(output_item)
                error_count += 1
                input_filenames[upload_type] = []
                continue

        available_filenames[upload_type] = input_filenames[upload_type].copy() if len(input_filenames[upload_type]) > 0 else []

         # remove invalid files
        for filename in input_filenames[upload_type]:
            is_duplicate = input_filenames[upload_type].count(filename) > 1
            if is_duplicate:
                status = 'ERROR: DUPLICATE FILE'
                error = f'Duplicate filename {filename}'
            elif extension_error := _invalid_extension_error(upload_type, filename):
                status = 'ERROR: INVALID EXTENSION'
                error = extension_error
            else:
                continue
            output_item = {
                upload_type: filename,
                'status': status,
                'error': error
            }
            output_data.append(output_item)
            error_count += 1
            available_filenames[upload_type].remove(filename)
    
        input_filenames[upload_type] = available_filenames[upload_type].copy()

    # prepare output dictionary with image filenames as keys
    output_dictionary = {}
    if not isinstance(input_filenames['image'], str):
        for filename in input_filenames['image']:
            output_dictionary[filename] = {}

    # loop through and match with an image
    for upload_type in ['mask', 'csv']:

        image_filenames = input_filenames['image']

        # get all pairwise distances between filenames

        # first, extract the stem:
        start_time = perf_counter()
        def _get_stems(filenames):
            return [os.path.splitext(os.path.basename(f))[0] for f in filenames]
        image_stems = _get_stems(image_filenames)
        available_stems = _get_stems(available_filenames[upload_type])
        current_app.logger.info(f'Extracting stems done in {round(perf_counter()-start_time,1)} seconds')

        current_app.logger.info(f'Comparing filenames...')
        start_time = perf_counter()
        distances = np.zeros([len(image_stems), len(available_stems)], dtype=float)
        for row, image_filename in enumerate(image_stems):
            upload_progress[session_id] = row / len(image_stems)
            upload_progress[session_id] *= 0.9
            for col, filename in enumerate(available_stems):
                distances[row, col] = -fuzz.ratio(image_filename, filename)
        current_app.logger.info(f'Comparing filenames done in {round(perf_counter()-start_time,1)} seconds')

        start_time = perf_counter()
        current_app.logger.info(f'Matching filenames...')
        for _ in range(distances.size):

            try:
                # find smallest distance in the pairwise distance matrix
                min_row, min_col = np.unravel_index(np.nanargmin(distances), distances.shape)
            except ValueError:
                # no more non-nan pairwise distances left
                break

            # pull the associated data
            matched_image = image_filenames[min_row]
            matched_filename = input_filenames[upload_type][min_col]

            # store it with the image as the key
            output_dictionary[matched_image][upload_type] = matched_filename

            # make that row/col NaN
            distances[min_row,:] = np.nan
            distances[:,min_col] = np.nan

            # remove it from the available filenames
            available_filenames[upload_type].remove(matched_filename)
        
        # all the remaining available filenames have no associated image
        for filename in available_filenames[upload_type]:
            output_item = {
                upload_type: filename,
                'status': 'ERROR: UNUSED FILE',
                'error': f'{upload_type} {filename} has no associated image.'
            }
            output_data.append(output_item)
            error_count += 1
        current_app.logger.info(f'Matching filenames done in {round(perf_counter()-start_time,1)} seconds')

    # convert to output format
    for image_filename, extra_data in output_dictionary.items():
        output_item = {
            'image': image_filename,
            'status': 'READY TO IMPORT'
        }
        for extra_key, extra_value in extra_data.items():
            output_item[extra_key] = extra_value
        output_data.append(output_item)
    
    return output_data, error_count


def _get_session_upload_root(project_name, session_id):
    # to avoid malicious session id's (e.g. '../../../sys') we run it through SHA256
    session_subfolder = str(hashlib.sha256(session_id.encode()).hexdigest())
    # current_app.logger.debug(f'session_subfolder = {session_subfolder}')
    upload_root = os.path.join('projects', project_name, 'uploads', session_subfolder)
    # current_app.logger.debug(f'upload_root = {upload_root}')
    return upload_root
    

def _get_session_upload_subfolder(project_name, session_id, upload_type):
    upload_root = _get_session_upload_root(project_name, session_id)
    upload_subfolder = os.path.join(upload_root, upload_type)
    # current_app.logger.debug(f'upload_subfolder = {upload_subfolder}')
    return upload_subfolder


    
# this function gets called multiple times in parallel with small batches of uploads
@upload_modal.route('/upload/<project_name>/<session_id>/<upload_type>/', methods=['POST'])
def upload(project_name, session_id, upload_type):

    if Project.query.filter_by(name=project_name).first() is None:
        return f'Project {project_name} not found', 400

    output_subfolder = _get_session_upload_subfolder(project_name, session_id, upload_type)
    if not os.path.isdir(output_subfolder):
        # current_app.logger.info('Creating output subfolder...')
        os.makedirs(output_subfolder)
        # current_app.logger.info('Created output subfolder.')

    for file in request.files.values():
        output_filename = os.path.join(output_subfolder, file.filename)
        # current_app.logger.debug(f'output_filename = {output_filename}')
        # current_app.logger.info('Saving file...')
        file.save(output_filename)
        # current_app.logger.info('Saved file.')
    
    return {'uploaded_count': len(request.files)}


upload_progress = {}


def _get_image_size(path):

    # current_app.logger.debug(f'Loading image {path}...')
    image = PIL.Image.open(path)
    # current_app.logger.debug(f'Loaded image {path}.')

    width = image.size[0]
    height = image.size[1]
    # current_app.logger.debug(f'width = {width}')
    # current_app.logger.debug(f'height = {height}')

    return width, height


def _get_mask_matrix(path):
    matrix = np.array(PIL.Image.open(path))
    if not (matrix.ndim == 2 or matrix.ndim == 3):
        raise ValueError(f'Invalid mask dimensions {matrix.ndim}')
    if matrix.ndim == 3:
        channels = matrix.shape[2]
        if channels > 3:
            matrix = matrix[:,:,0:3]
        elif channels == 2:
            raise ValueError(f'Invalid mask shape {matrix.shape}')
        elif channels < 2:
            matrix = matrix[:,:,0]
    uniques = np.sort(np.unique(matrix))
    return matrix, uniques


def _validate_index_mask(path):
    mask, _ = _get_mask_matrix(path)
    if skimage.measure.label(mask).max() != len(skimage.measure.regionprops(mask)):
        raise ValueError(f'Validation check failed (skimage.measure.label(mask).max() == len(skimage.measure.regionprops(mask)))')


def _validate_labeled_mask(path, project_name):
    mask, _ = _get_mask_matrix(path)

    if mask.ndim == 2:
        unique_labels = np.expand_dims(np.unique(mask.flatten()),1)
    else:
        unique_labels = np.unique(mask.reshape(-1, mask.shape[2]), axis=0) # https://stackoverflow.com/a/48904991
    is_black = np.all(unique_labels == 0, axis=1)
    num_unique_colors = np.sum(~is_black)

    num_classes = Project.query.filter_by(name=project_name).first().no_of_label_type

    if num_unique_colors > num_classes:
        raise ValueError(f'Project {project_name} can only support {num_classes} classes, but {path} has {num_unique_colors} unique labels.')


def _validate_binary_mask(path):
    _, uniques = _get_mask_matrix(path)
    if len(uniques) != 2:
        raise ValueError(f'For binary masks, we expect exactly 2 unique values (zero and non-zero). {path} has {len(uniques)} unique values.')
    if uniques[0] != 0:
        raise ValueError('Binary masks expect at least some pixels to have a value of zero. All your pixels have values {uniques}')


def _validate_quick_annotator_mask(path):
    mask, uniques = _get_mask_matrix(path)
    if not (np.all(uniques == [0,255]) or np.all(uniques == [False, True])):
        raise ValueError(f'Quick Annotator masks must either be a binary mask or have exactly two unique values: 0 and 255, but {path} has {len(uniques) if len(uniques)>2 else uniques}')

    if mask.ndim == 3:
        unique_rgb_codes = np.unique(mask.reshape(-1, mask.shape[2]), axis=0).tolist()
        # black , unknown color , turquoise(positive) , (fuchsia)negative color.
        valid_rgb_codes = [[0, 0, 0], [0, 0, 255], [0, 255, 255], [255, 0, 255]]
        check_valid_rgb = all(rgb_code in valid_rgb_codes for rgb_code in unique_rgb_codes)
        if check_valid_rgb is False:
            raise ValueError(f'Invalid rgb_code in mask, valid rgb_codes are [0, 0, 0], [0, 0, 255], [0, 255, 255], [255, 0, 255]')
    """
        Masks from Quick Annotator

        https://github.com/choosehappy/QuickAnnotator/blob/8a4a9b1bfcf51bc67e3949a990fe524b05606959/cli/import_annotations_cli.py#L138

        note those masks are loaded as BGR instead of RGB
        https://github.com/choosehappy/QuickAnnotator/issues/17

        Third channel

        toupload[:,:,2]=255
        toupload[:,:,0]=(mask[:,:,2]>0)*255
        toupload[:,:,1]=(mask[:,:,1]>0)*255
    """


def _check_valid_mask(path, width, height, mask_type, project_name):

    # first validate size
    mask_width, mask_height = _get_image_size(path)
    if mask_width != width or mask_height != height:
        raise ValueError(f'[Invalid Size] Mask size was {mask_width}×{mask_height} (w × h) but the image size was {width}×{height}!')
    
    # then validate contents
    if mask_type == MaskTypeEnum.QA:
        _validate_quick_annotator_mask(path)
    elif mask_type == MaskTypeEnum.Binary:
        _validate_binary_mask(path)
    elif mask_type == MaskTypeEnum.Indexed:
        _validate_index_mask(path)
    elif mask_type == MaskTypeEnum.Labeled:
        _validate_labeled_mask(path, project_name)
    else:
        raise ValueError(f'Unknown mask type {mask_type}')
    

def _move_uploaded_file(project_name, session_id, upload_type, filename, files_to_roll_back):
    session_subfolder = _get_session_upload_subfolder(project_name, session_id, upload_type)
    # current_app.logger.debug(f'session_subfolder = {session_subfolder}')
    from_path = os.path.join(session_subfolder, filename)
    # current_app.logger.debug(f'from_path = {from_path}')

    to_path = os.path.join('projects', project_name)
    if upload_type != 'image':
        to_path = os.path.join(to_path, upload_type)
    to_path = os.path.join(to_path, filename)
    # current_app.logger.debug(f'to_path = {to_path}')

    if os.path.exists(to_path):
        error_message = f'{upload_type} {os.path.basename(to_path)} already exists for project {project_name}. No duplicates allowed.'
        current_app.logger.warning(error_message)
        raise ValueError(error_message)
    
    os.rename(from_path, to_path)

    return to_path


def _process_upload(paths, project_id, project_name, session_id, from_dropzone, mask_type):
    mask_path = None
    csv_path = None

    # in case an image is accepted but a mask fails, we must delete the already-moved image
    dropzone_files_to_roll_back = []

    try:
        # loop through the upload types and get the paths for each oen
        for upload_type, filename in paths.items():

            # current_app.logger.debug(f'upload_type = {upload_type}')
            # current_app.logger.debug(f'filename = {filename}')

            # if this upload type is not even in the from_dropzone dictionary, it's likely a path to a remote folder
            if not upload_type in from_dropzone:
                # skip it
                continue

            if from_dropzone[upload_type]:
                # files from a dropzone need to have their upload extension prepended
                path = _move_uploaded_file(project_name, session_id, upload_type, filename, dropzone_files_to_roll_back)
                dropzone_files_to_roll_back.append(path)
            else:
                # files that came from a csv list should be absolute paths already
                path = filename
            # current_app.logger.debug(f'path = {path}')

            # extension check!
            if extension_error := _invalid_extension_error(upload_type, path):
                raise ValueError(extension_error)
            
            # assign variables
            if upload_type == 'image':
                image_path = path
                image_name = os.path.basename(path)
                width, height = _get_image_size(path)
            elif upload_type == 'mask':
                mask_path = path
            elif upload_type == 'csv':
                csv_path = path

        if mask_path is not None:
            # current_app.logger.info('Checking if mask is valid...')
            _check_valid_mask(mask_path, width, height, mask_type, project_name)
            # current_app.logger.info('Mask is valid.')
    except Exception as error:
        current_app.logger.warning(str(error))
        for file_to_delete in dropzone_files_to_roll_back:
            current_app.logger.info(f'Deleting {file_to_delete} from server.')
            os.remove(file_to_delete)
        raise error # still need to re-raise it so it passes through to the parent except statement

    # current_app.logger.info('Adding image to database:')
    import_type = 'dropzone' if from_dropzone else 'file_list'
    new_database_row = Image(
        img_name    = image_name,
        img_path    = image_path,
        mask_path   = mask_path,
        mask_type   = mask_type if mask_path is not None else None,
        csv_path    = csv_path,
        projId      = project_id,
        width       = width,
        height      = height,
        import_type = import_type,
        date = datetime.utcnow())
    db.session.add(new_database_row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ValueError(f'An image named {image_name} already exists for project {project_name}. No duplicates allowed.')

    # current_app.logger.info('Added image to database.')


@upload_modal.route('/upload/<project_name>/<session_id>/process/', methods=['POST'])
def process_uploads(project_name, session_id):
    t_start_upload = perf_counter()
    # current_app.logger.debug(f'session_id = {session_id}')

    request_data = request.get_json()
    # current_app.logger.debug(f'request_data = {request_data}')

    input_paths = request_data['paths']
    output_data = input_paths.copy()

    mask_type = MaskTypeEnum(request_data['mask_type'])
    # current_app.logger.debug(f'mask_type = {mask_type}')

    # each upload type is either a collection of files from a dropzone or a path to a remote folder
    from_dropzone = {}
    for upload_type in ['image', 'mask', 'csv']:
        from_dropzone[upload_type] = (not request_data['list']) and (not request_data[upload_type + '_is_folder'])
    # current_app.logger.debug(f'from_dropzone = {from_dropzone}')

    project = Project.query.filter_by(name=project_name).first()
    if project is None:
        return f'Project {project_name} not found', 400

    upload_progress[session_id] = 0
    for i, (current_input_paths, output_paths) in enumerate(zip(input_paths, output_data)):
        progress = i / len(input_paths)
        upload_progress[session_id] = progress
        current_app.logger.info(f'Processing progress = {progress}')
        current_app.logger.debug(f'current_input_paths = {current_input_paths}')
        try:
            _process_upload(current_input_paths, project.id, project_name, session_id, from_dropzone, mask_type)
            output_paths['status'] = 'IMPORTED'
            # current_app.logger.info('Processed upload.')
        except Exception as error:
            output_paths['status'] = 'IMPORT ERROR'
            error = str(type(error).__name__) + ': ' + str(error)
            output_paths['error'] = error
            current_app.logger.error(error)

    # reset progress to zero
    upload_progress[session_id] = 1

    # delete upload folder
    upload_folder = _get_session_upload_root(project_name, session_id)
    if os.path.isdir(upload_folder):
        current_app.logger.debug(f'Deleting {upload_folder}.')
        rmtree(upload_folder)
    t_end_upload = perf_counter()
    print(f"Time taken to upload these files {t_end_upload-t_start_upload}")
    # output any status messages for each file processed
    return {'paths': output_data}


@upload_modal.route('/upload/<session_id>/progress/', methods=['GET'])
def get_progress(session_id):

    # initialize
    if session_id not in upload_progress.keys():
        upload_progress[session_id] = 0

    progress = upload_progress[session_id]
    is_complete = progress >= 1
    data = {'progress': progress, 'is_complete': is_complete}
    return data
