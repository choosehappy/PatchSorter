#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat May 30 01:05:59 2020
@author: siddhesh
"""


from setuptools import setup
import setuptools

setup(
    name="PatchSorter",
    version="1.0.0",
    description="PatchSorter is an open-source digital pathology tool for histologic object labeling.",
    url="https://github.com/choosehappy/PatchSorter",
    python_requires=">=3.8",
    author="choosehappy",
    author_email="None",
    license="BSD-3-Clause",
    zip_safe=False,
    install_requires=[
        "torch>=1.8.2",
    ],
    scripts=[
        "PatchSorter_run",
    ],
    classifiers=[
        "Intended Audience :: Science/Research",
        "Programming Language :: Python",
        "Topic :: Digital Pathology",
        "Operating System :: Unix",
    ],
    packages=setuptools.find_packages(),
    include_package_data=True,
)
