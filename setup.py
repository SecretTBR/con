from setuptools import setup

def get_requirements():
    with open('requirements.txt') as f:
        return f.read().splitlines()

setup(
    name="blackrussia_converter",
    version="1.0.0",
    install_requires=get_requirements(),
)