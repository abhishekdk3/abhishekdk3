#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
# these imports are sorted this way for a reason
# flake8: noqa F821
# pylint: skip-file
# isort: skip_file
"""
This module is used to filter and reload PATH.
"""
import import_declare_test
import os
import sys

try:
    if os.name == "nt" and sys.version_info[0] > 2:
        # for Windows and python3 only
        PYTHON = "Python"
        default_path = [path for path in sys.path if PYTHON in path]
        default_path.extend(sys.path)
        sys.path = default_path
    import http
    import queue
    import copyreg
    import re
    import html
    import configparser
    import http.client
except:
    pass

import os.path
import re
import types
import logging
import httplib2_helper


def setup_python_path():
    # Exclude folder beneath other apps, Fix bug for rest_handler.py
    ta_name = os.path.basename(os.path.dirname(os.path.dirname(__file__)))
    pattern = re.compile(r"[\\/]etc[\\/]apps[\\/][^\\/]+[\\/]bin[\\/]?$")
    new_paths = [
        path for path in sys.path if not pattern.search(path) or ta_name in path
    ]
    new_paths.insert(0, os.path.dirname(__file__))
    sys.path = new_paths

    bindir = os.path.dirname(os.path.abspath(__file__))
    # We sort the precedence in a decending order since sys.path.insert(0, ...)
    # do the reversing.
    # Insert library folder
    path_to_lib = os.path.join(os.path.dirname(bindir), "lib")
    sys.path.insert(0, path_to_lib)
    if sys.version_info[0] < 3:
        path_to_py2_modules = os.path.join(path_to_lib, "py2_modules")
        sys.path.insert(0, path_to_py2_modules)
    path_to_splunktalib = os.path.join(path_to_lib, "splunktalib_helper")
    sys.path.insert(0, path_to_splunktalib)
    load_google_cloud_package(path_to_lib)


def load_google_cloud_package(sitedir):
    def _load_virtual_package(*path):
        folder = os.path.join(sitedir, *path)
        if not os.path.isdir(folder):
            return
        name = ".".join(path)
        package = sys.modules.setdefault(name, types.ModuleType(name))
        package.__dict__.setdefault("__path__", [folder])
        if len(path) > 1:
            pname = ".".join(path[:-1])
            mname = path[-1]
            setattr(sys.modules[pname], mname, package)

    _load_virtual_package("google")
    _load_virtual_package("google", "iam")
    _load_virtual_package("google", "logging")
    _load_virtual_package("google", "cloud")
    _load_virtual_package("google", "cloud", "gapic")
    _load_virtual_package("google", "cloud", "gapic", "pubsub")
    _load_virtual_package("google", "cloud", "proto")
    _load_virtual_package("google", "cloud", "proto", "pubsub")


def run_module(name):
    setup_python_path()
    instance = __import__(name, fromlist=["main"])
    instance.main()


# preventing splunklib initialize an unexpected root handler
def run_rest_handler(name):
    logging.root.addHandler(logging.NullHandler())
    run_module(name)


setup_python_path()
