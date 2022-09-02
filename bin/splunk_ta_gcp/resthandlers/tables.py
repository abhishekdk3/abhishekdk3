#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

import logging

import splunk.admin as admin
import splunk.clilib.cli_common as scc
import splunk_ta_gcp.legacy.config as gconf
import splunk_ta_gcp.legacy.consts as ggc
import splunktalib.common.pattern as scp
from splunk_ta_gcp.legacy.common import create_google_client
from splunktalib.common import util

logger = logging.getLogger()

util.remove_http_proxy_env_vars()


class GoogleDatasets(admin.MConfigHandler):
    valid_params = [
        ggc.google_credentials_name,
        ggc.google_project,
        ggc.google_bq_dataset,
    ]

    def setup(self):
        for param in self.valid_params:
            self.supportedArgs.addOptArg(param)

    @scp.catch_all(logger)
    def handleList(self, conf_info):
        logger.info("start listing google subscriptions")
        for required in self.valid_params:
            if not self.callerArgs or not self.callerArgs.get(required):
                logger.error('Missing "%s"', required)
                raise Exception('Missing "{}"'.format(required))

        stanza_name = self.callerArgs[ggc.google_credentials_name][0]
        config = gconf.get_google_settings(
            scc.getMgmtUri(), self.getSessionKey(), cred_name=stanza_name
        )

        project = self.callerArgs[ggc.google_project][0]
        dataset_id = self.callerArgs[ggc.google_bq_dataset][0]
        config.update(
            {
                "service_name": "bigquery",
                "version": "v2",
                "scopes": ["https://www.googleapis.com/auth/cloud-platform.read-only"],
            }
        )
        bigquery_client = create_google_client(config)

        tables = bigquery_client.tables()
        tables_names = list()
        request = tables.list(projectId=project, datasetId=dataset_id)
        while request:
            response = request.execute()
            names = [
                table["tableReference"]["tableId"] for table in response.get("tables")
            ]
            tables_names.extend(names)
            request = tables.list_next(request, response)

        for tables_name in tables_names:
            conf_info[tables_name].append("tables", tables_name)

        logger.info("end of listing google subscriptions")


def main():
    admin.init(GoogleDatasets, admin.CONTEXT_NONE)
