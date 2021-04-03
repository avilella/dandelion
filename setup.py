from setuptools import setup, find_packages

with open("README.md", "r") as readme_file:
    readme = readme_file.read()
# exec(open('dandelion/version.py').read())

with open("requirements_dev.txt", "rt", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh.readlines()]

setup(
    name="sc-dandelion",
    use_scm_version={
        'write_to': 'dandelion/logging/version.py',
        'write_to_template': "# coding: utf-8\n# file generated by setuptools_scm\n# don't change, don't track in version control\n__version__ = {version}.split['+'][0]",
        'tag_regex': r'^(?P<prefix>v)?(?P<version>[^\+]+)(?P<suffix>.*)?$',
    },
    # use_scm_version=False,
    # version = __version__,
    author="zktuong",
    author_email="kt16@sanger.ac.uk",
    description="sc-BCR analysis tool",
    long_description=readme,
    long_description_content_type="text/markdown",
    url="https://github.com/zktuong/dandelion/",
    packages=find_packages(),
    setup_requires=["setuptools>=45", "wheel", "setuptools_scm[toml]>=6.0"],
    install_requires=requirements,
    package_data={'dandelion': ['bin/tigger-genotype.R']},
    data_files=[('bin', ['bin/tigger-genotype.R'])],
    include_package_data=True,
    classifiers=[
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: R",
        "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)",
    ],
    zip_safe=False
)
