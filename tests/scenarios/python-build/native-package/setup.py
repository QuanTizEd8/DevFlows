"""setuptools shim declaring the single C extension.

Project metadata lives in pyproject.toml; only the ext_modules (which setuptools
cannot yet take from pyproject) need this file. Building this package therefore
produces a platform wheel, which is what the cibuildwheel scenario exercises.
"""

from setuptools import Extension, setup

setup(
    ext_modules=[
        Extension(
            "devflows_cext_fixture._speedup",
            ["src/devflows_cext_fixture/_speedup.c"],
        )
    ],
)
