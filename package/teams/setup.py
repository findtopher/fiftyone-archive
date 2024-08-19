#!/usr/bin/env python
"""
Installs FiftyOne Teams App

| Copyright 2017-2023, Voxel51, Inc.
| `voxel51.com <https://voxel51.com/>`_
|
"""
import os
from pkg_resources import DistributionNotFound, get_distribution
import re
from setuptools import setup

INSTALL_REQUIRES = [
    "python-jose>=3.3.0,<4",
    "fiftyone>2.0,<2.2",
]


CHOOSE_INSTALL_REQUIRES = []


def choose_requirement(mains, secondary):
    chosen = secondary
    for main in mains:
        try:
            name = re.split(r"[!<>=]", main)[0]
            get_distribution(name)
            chosen = main
            break
        except DistributionNotFound:
            pass

    return str(chosen)


def get_install_requirements(install_requires, choose_install_requires):
    for mains, secondary in choose_install_requires:
        install_requires.append(choose_requirement(mains, secondary))

    return install_requires


with open("README.md", "r") as fh:
    long_description = fh.read()


setup(
    name="fiftyone-teams-app",
    version="2.1.0.dev8",
    description=("FiftyOne Teams"),
    author="Voxel51, Inc.",
    author_email="info@voxel51.com",
    url="https://github.com/voxel51/fiftyone",
    long_description=long_description,
    long_description_content_type="text/markdown",
    packages=["fiftyone.teams"],
    include_package_data=True,
    install_requires=get_install_requirements(
        INSTALL_REQUIRES, CHOOSE_INSTALL_REQUIRES
    ),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: Apache Software License",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Scientific/Engineering :: Image Processing",
        "Topic :: Scientific/Engineering :: Image Recognition",
        "Topic :: Scientific/Engineering :: Information Analysis",
        "Topic :: Scientific/Engineering :: Visualization",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX :: Linux",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
    python_requires=">=3.7",
)
