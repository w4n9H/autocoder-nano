import os
#from jinja2.runtime import V
from setuptools import find_packages
from setuptools import setup

folder = os.path.dirname(__file__)
version_path = os.path.join(folder, "src", "autocoder_nano", "version.py")

__version__ = ""
with open(version_path) as f:
    exec(f.read(), globals())

req_path = os.path.join(folder, "requirements.txt")
install_requires = []
if os.path.exists(req_path):
    with open(req_path, 'r') as fp:
        install_requires = [line.strip() for line in fp]


readme_path = os.path.join(folder, "README.md")
readme_contents = ""
if os.path.exists(readme_path):
    with open(readme_path, 'r') as fp:
        readme_contents = fp.read().strip()


setup(
    name="autocoder_nano",
    version=__version__,
    description="AutoCoder Nano",
    author="moofs",
    long_description=readme_contents,
    long_description_content_type="text/markdown",
    entry_points={
        'console_scripts': [
            'auto-coder.nano = autocoder_nano.auto_coder_nano:main',
        ],
    },
    package_dir={"": "src"},
    packages=find_packages("src"),
    package_data={
        "autocoder_nano": [
            "data/**/*",
            'agent/prompt/**/*'
        ],
    },
    install_requires=install_requires,
    classifiers=[
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11"
    ],
    python_requires=">=3.10"
)
