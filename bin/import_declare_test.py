#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

import os
import sys

path_to_lib = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"
)
sys.path.insert(0, path_to_lib)
if sys.version_info[0] < 3:
    path_to_py2_modules = os.path.join(path_to_lib, "py2_modules")
    sys.path.insert(0, path_to_py2_modules)
path_to_splunktalib = os.path.join(path_to_lib, "splunktalib_helper")
sys.path.insert(0, path_to_splunktalib)
