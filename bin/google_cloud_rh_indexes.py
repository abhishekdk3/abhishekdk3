#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
from google_cloud_bootstrap import run_rest_handler
from splunksdc import log as logging
from splunktaucclib.rest_handler.error_ctl import RestHandlerError as RH_Err

if __name__ == "__main__":
    try:
        run_rest_handler("splunk_ta_gcp.resthandlers.indexes")
    except BaseException as exc:
        RH_Err.ctl(-1, exc, logLevel=logging.ERROR, shouldPrint=False)
