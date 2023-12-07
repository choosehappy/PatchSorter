import glob
import os.path
from setuptools import setup

setup(
    use_scm_version={
        # duplicated config from pyproject.toml; keep in sync
        "write_to": "patchsorter/_version.py",
        "version_scheme": "post-release",
    },
    setup_requires=['setuptools_scm'],

)