#!/usr/bin/python
#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

"""
This is the main entry point for My TA
"""

import time
from builtins import str

import httplib2shim
import splunk_ta_gcp.legacy.common as tacommon
import splunktalib.common.pattern as gcp
import splunktalib.data_loader_mgr as dlm
from splunksdc import log as logging

from . import config as mconf
from . import consts as grc
from . import data_loader as grdl

logger = logging.get_module_logger()


def print_scheme():
    title = "Splunk Add-on for Google Cloud Platform"
    description = "Collect and index Google Cloud Resource Metadata data"
    tacommon.print_scheme(title, description)


@gcp.catch_all(logger)
def run():
    """
    Main loop. Run this TA forever
    """
    logger.info("Start google_resource_metadata")
    metas, tasks = tacommon.get_configs(
        mconf.GoogleResourceMetadataConfig, "google_resource_metadata", logger
    )

    if not tasks:
        return

    logger.debug("Recieved " + str(len(tasks)) + " Tasks.")

    metas[grc.log_file] = grc.description_log
    loader_mgr = dlm.create_data_loader_mgr(metas)
    tacommon.setup_signal_handler(loader_mgr, logger)
    conf_change_handler = tacommon.get_file_change_handler(loader_mgr, logger)
    conf_monitor = tacommon.create_conf_monitor(
        conf_change_handler, [grc.myta_data_collection_conf]
    )

    time.sleep(5)
    loader_mgr.add_timer(conf_monitor, time.time(), 10)
    jobs = [grdl.ResourceDataLoader(task) for task in tasks]
    loader_mgr.start(jobs)

    logger.info("End google_resource_metadata")


def main():
    """
    Main entry point
    """
    httplib2shim.patch()
    logging.setup_root_logger(
        "splunk_ta_google-cloudplatform", "google_cloud_resource_metadata"
    )
    tacommon.main(print_scheme, run)
