import logging
import os
import shutil
from logging import config
from multiprocessing import Pool

from flask import Flask
from flask_restless import APIManager, ProcessingException
from waitress import serve
from sqlalchemy import delete
import signal



import PS_db
from PS_api import api_blueprint
from PS_api_image import delete_image
from PS_api_project_helper import delete_label
from PS_config import config, get_database_uri
from PS_db import db, Image, Project, Job, Labelnames, Metrics, create_newproj_dir, check_projectexists, setup_flask_admin, SearchCache
from PS_html import html
from PS_api_image_upload import upload_modal


def add_project(**kw):
    projectName = kw['result']['name']
    noLabel = int(kw['result']['no_of_label_type'])
    projId = kw['result']['id']
    create_newproj_dir(projectName,noLabel,projId)
    return kw


def delete_project(instance_id=None, **kw):  # should really be a postprocess but no instance ID is available
    # Delete all images in the project, this function removes the relational foreign keys as well
    proj = Project.query.filter_by(id=instance_id).first()

    selected_images = db.session.query(Image).filter_by(projId=proj.id)
    for selected_image in selected_images:
        delete_image(proj.name, selected_image.img_name)

    selected_labels = db.session.query(Labelnames).filter_by(projId=proj.id)
    for selected_label in selected_labels:
        delete_label(proj.name, selected_label.label_id)

    #delete jobs
    selected_Jobs = db.session.query(Job).filter_by(projId=proj.id)
    selected_Jobs.delete()

    db.session.query(Metrics).filter_by(projId=proj.id).delete()



    # Check if the project folder exists
    shutil.rmtree(os.path.join("projects", proj.name), ignore_errors=True)

    pass


# For the preprocessor to raise an exception if a duplicate project name is posted.
def check_existing_project(data):
    project_name = data['name']
    noLabels = data.get('no_of_label_type')
    if not check_projectexists(project_name):
        try:
            if noLabels == None or noLabels == " " or noLabels == "":
                data['no_of_label_type'] = 2
            elif int(noLabels) < 2:
                data['no_of_label_type'] = 2
            elif int(noLabels) > 10:
                raise ProcessingException(description=f'Project [{project_name}] require labels between(1-10).', code=400)
        except ValueError:
            raise ProcessingException(description=f'Project [{project_name}] require labels between(1-10).', code=400)


def init_worker():
    signal.signal(signal.SIGINT, signal.SIG_IGN)

if __name__ == '__main__': #This seems like the correct place to do this

    # Create the Flask-Restless API manager
    app = Flask(__name__)
#    app.debug = True
    app.logger_name = 'flask'
    app.register_blueprint(html)
    app.register_blueprint(upload_modal)
    app.register_blueprint(api_blueprint)

    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.config['SQLALCHEMY_DATABASE_URI'] = get_database_uri()
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SQLALCHEMY_ECHO'] = config.getboolean('sqlalchemy', 'echo', fallback=False)
    app.config['CACHE_TYPE'] = "SimpleCache"
    SearchCache.init_app(app)

    APP_ROOT = os.path.dirname(os.path.abspath('__file__'))
    # load logging config is moved to PS_Config
    # logging.config.fileConfig('./config/logging.ini')

    app.logger.info('Initializing database')

    db.app = app
    db.init_app(app)
    db.create_all()
    db.engine.connect().execute('pragma journal_mode=wal;')

    if config.getboolean('sqlalchemy', 'delete_old_jobs_at_start', fallback=True):
        jobid_tables = db.session.execute("SELECT name FROM sqlite_master WHERE type='table' and name like 'jobid_%' ORDER BY name").fetchall()
        for jobid_table in jobid_tables:
            app.logger.info(f'Dropping jobid_table {jobid_table[0]}')
            db.session.execute(f"DROP TABLE IF EXISTS {jobid_table[0]}")

        db.session.commit()



    # ----
    app.logger.info('Clearing stale jobs')
    if config.getboolean('flask', 'clear_stale_jobs_at_start', fallback=True):
        njobs = PS_db.clear_stale_jobs()  # <-- clear old queued jobs from last session
        db.session.commit()
        app.logger.info(f'Deleted {njobs} queued jobs.')

    # ----
    app.apimanager = APIManager(app, flask_sqlalchemy_db=db)
    #
    # # Create API endpoints, which will be available at /api/<tablename> by default
    app.apimanager.create_api(Project, methods=['GET', 'POST', 'DELETE', 'PUT'], url_prefix='/api/db',
                       results_per_page=0, max_results_per_page=0,
                       preprocessors={'DELETE_SINGLE': [delete_project], 'POST': [check_existing_project]},
                       postprocessors={'POST': [add_project]})
    #,'PATCH_SINGLE':[check_update_project]})



    app.apimanager.create_api(Labelnames, methods=['GET', 'POST', 'DELETE', 'PUT'], url_prefix='/api/db',
                       results_per_page=0, max_results_per_page=0,)


    app.apimanager.create_api(Image, methods=['GET', 'POST', 'DELETE', 'PUT'], url_prefix='/api/db',
                       results_per_page=0, max_results_per_page=0,)

    app.apimanager.create_api(Job, methods=['GET', 'POST', 'DELETE', 'PUT'], url_prefix='/api/db',
                       results_per_page=0, max_results_per_page=0,)


    #--- setup flask admin
    setup_flask_admin(app)

    app.logger.info('Starting up worker pool.')

    PS_db._pool = Pool(processes=config.getint('pooling', 'npoolthread', fallback=4),initializer=init_worker)

    try:

        serve(app, host='0.0.0.0', port=config.getint('flask', 'port', fallback=5555),
               threads=config.getint('flask', 'threads', fallback=8),)

#    app.run( host='0.0.0.0', port=config.getint('flask', 'port', fallback=5555))
    #       threads=config.getint('flask', 'threads', fallback=8),)
    except KeyboardInterrupt:
        print("Caught KeyboardInterrupt, terminating workers")
        PS_db._pool.terminate()
        PS_db._pool.join()

    else:
        print("PS application terminated by user")
        PS_db._pool.close()
        PS_db._pool.join()