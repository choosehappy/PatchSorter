# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# Make the patchsorter package importable by autodoc
sys.path.insert(0, os.path.abspath('../..'))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'PatchSorter'
copyright = '2025, Andrew Janowczyk'
author = 'Andrew Janowczyk'
release = '1.0'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx_design',
    'myst_parser',
    'sphinxcontrib.mermaid',
    'sphinxarg.ext'
]

myst_enable_extensions = [
    "tasklist"
]

# Allow .md files as source
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

templates_path = ['_templates']
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']



# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'furo'
html_static_path = ['_static']

# Add custom JavaScript to set dark mode as default
html_js_files = [
    'set_default_dark_mode.js',
]

# Add custom CSS for further customization
html_css_files = [
    'custom.css',
]

autodoc_mock_imports = [
    "torch", "ray", "pandas", "pillow",
    "sqlalchemy", "psycopg", "tensorboardx", "pyarrow",
    "geoalchemy2", "gdal", "shapely", "osgeo",
    "fastapi", "uvicorn", "numpy", "matplotlib", "large_image",
]

# sphinx-argparse doesn't support parallel reads
sphinx_parallel_read_safe = False