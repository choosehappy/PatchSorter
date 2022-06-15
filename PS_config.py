import configparser
import logging
from logging import config
#Needs to be done here instead of PS.py else the root logger is set to WARNING.
logging.config.fileConfig('./config/logging.ini')

config_logger = logging.getLogger('root')

# initialize a new config file:
config = configparser.ConfigParser(interpolation=configparser.ExtendedInterpolation())

# read the options from disk:
config.read("./config/config.ini")

# display:
config_logger.info(f'Config sections = {config.sections()}')

def get_database_uri():
  return config.get('sqlalchemy', 'database_uri', fallback='sqlite:///patch_sorter_data.db')
