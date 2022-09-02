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

import httplib2shim
import splunk_ta_gcp.legacy.common as tacommon
import splunktalib.common.pattern as gcp
import splunktalib.data_loader_mgr as dlm
from splunksdc import log as logging

from . import config as mconf
from . import consts as gmc
from . import data_loader as gmdl

logger = logging.get_module_logger()


def print_scheme():
    title = "Splunk AddOn for Google"
    description = "Collect and index Google Cloud Monitor data"
    tacommon.print_scheme(title, description)


@gcp.catch_all(logger)
def run():
    """
    Main loop. Run this TA forever
    """

    logger.info("Start google_cloud_monitor")
    metas, tasks = tacommon.get_configs(
        mconf.GoogleCloudMonitorConfig, "google_cloud_monitor", logger
    )

    if not tasks:
        return

    loader_mgr = dlm.create_data_loader_mgr(tasks[0])
    tacommon.setup_signal_handler(loader_mgr, logger)

    conf_change_handler = tacommon.get_file_change_handler(loader_mgr, logger)
    conf_monitor = tacommon.create_conf_monitor(
        conf_change_handler, [gmc.myta_data_collection_conf]
    )

    time.sleep(5)
    loader_mgr.add_timer(conf_monitor, time.time(), 10)

    jobs = [gmdl.GoogleCloudMonitorDataLoader(task) for task in tasks]
    loader_mgr.start(jobs)
    logger.info("End google_cloud_monitor")


def main():
    """
    Main entry point
    """
    httplib2shim.patch()
    logging.setup_root_logger(
        "splunk_ta_google-cloudplatform", "google_cloud_monitoring"
    )
    tacommon.main(print_scheme, run)
