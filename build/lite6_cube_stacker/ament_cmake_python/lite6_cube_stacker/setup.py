from setuptools import find_packages
from setuptools import setup

setup(
    name='lite6_cube_stacker',
    version='1.0.0',
    packages=find_packages(
        include=('lite6_cube_stacker', 'lite6_cube_stacker.*')),
)
