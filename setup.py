from setuptools import setup, find_packages


setup(
    name="clickable-stream-widget",
    version="1.0.0",
    packages=find_packages(),
    install_requires=['websockets'],
    package_data = {
        '': ['*']
    }
)