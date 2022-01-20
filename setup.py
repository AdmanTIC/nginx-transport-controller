# coding: utf-8

#install with
#python setup.py test
#python setup.py bdist_wheel

from setuptools import setup, find_packages

setup(
    name="nginx_transport_controller",
    version="0.0.1",
    author="admantic",
    packages=find_packages(),
    python_requires='>=3.8'
)
