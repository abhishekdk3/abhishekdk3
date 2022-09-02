#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
from __future__ import print_function

import logging

import googleapiclient
import splunk.admin as admin
import splunk.clilib.cli_common as scc
import splunk_ta_gcp.legacy.config as gconf
import splunk_ta_gcp.legacy.consts as ggc
import splunk_ta_gcp.legacy.resource_manager as grm
import splunktalib.common.pattern as scp
from splunktalib.common import util

logger = logging.getLogger()

util.remove_http_proxy_env_vars()


class GoogleProjects(admin.MConfigHandler):
    valid_params = [ggc.google_credentials_name]

    def setup(self):
        for param in self.valid_params:
            self.supportedArgs.addOptArg(param)

    @scp.catch_all(logger)
    def handleList(self, conf_info):
        logger.info("start list google projects")
        if not self.callerArgs or not self.callerArgs.get(ggc.google_credentials_name):
            logger.error("Missing Google credentials")
            raise Exception("Missing Google credentials")

        stanza_name = self.callerArgs[ggc.google_credentials_name][0]
        logger.info(self.callerArgs[ggc.google_credentials_name])
        config = gconf.get_google_settings(
            scc.getMgmtUri(), self.getSessionKey(), cred_name=stanza_name
        )
        res_mgr = grm.GoogleResourceManager(logger, config)
        try:
            projects = [project["projectId"] for project in res_mgr.projects()]
        except googleapiclient.errors.HttpError as e:
            if e.resp.status == 403:
                projects = [config[ggc.google_credentials]["project_id"]]
            else:
                raise e
        except Exception as e:
            print(e)
            raise BaseException()
        for project in projects:
            conf_info[project].append("projects", project)
        logger.info("end of listing google projects")


def main():
    admin.init(GoogleProjects, admin.CONTEXT_NONE)
