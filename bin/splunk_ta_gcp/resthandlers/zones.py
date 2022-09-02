#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import logging

import googleapiclient.discovery
import splunk.admin as admin
import splunk.clilib.cli_common as scc
import splunk_ta_gcp.legacy.config as gconf
import splunk_ta_gcp.legacy.consts as ggc
import splunktalib.common.pattern as scp
from splunk_ta_gcp.legacy.common import create_google_client
from splunktalib.common import util
from splunktaucclib.rest_handler.error_ctl import RestHandlerError as RH_Err

logger = logging.getLogger()

util.remove_http_proxy_env_vars()


class GoogleZones(admin.MConfigHandler):
    valid_params = [ggc.google_credentials_name, ggc.google_project]

    def setup(self):
        for param in self.valid_params:
            self.supportedArgs.addOptArg(param)

    @scp.catch_all(logger)
    def handleList(self, conf_info):
        logger.info("start listing google zones")
        for required in self.valid_params:
            if not self.callerArgs or not self.callerArgs.get(required):
                logger.error('Missing "%s"', required)
                raise Exception('Missing "{}"'.format(required))

        stanza_name = self.callerArgs[ggc.google_credentials_name][0]
        config = gconf.get_google_settings(
            scc.getMgmtUri(), self.getSessionKey(), cred_name=stanza_name
        )

        project = self.callerArgs[ggc.google_project][0]
        config[ggc.google_project] = project
        result = []
        config.update(
            {
                "service_name": "compute",
                "version": "v1",
                "scopes": ["https://www.googleapis.com/auth/compute"],
            }
        )
        storage = create_google_client(config)

        zones_names = storage.zones()
        request = zones_names.list(project=project)
        try:
            response = request.execute()
        except googleapiclient.errors.HttpError as exc:
            RH_Err.ctl(400, exc)
        names = [item.get("name") for item in response.get("items")]
        result.extend(names)
        for zone in result:
            conf_info[zone].append("zones", zone)
        logger.info("end of listing google zones")


def main():
    admin.init(GoogleZones, admin.CONTEXT_NONE)
