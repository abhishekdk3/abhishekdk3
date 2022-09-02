#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
"""
Get index list in SPlunk server.
"""

import json
import logging

from splunk import admin, rest
from splunktalib.common import util as common_util
from splunktaucclib.rest_handler import error_ctl, util

common_util.remove_http_proxy_env_vars()


class IndexHandler(admin.MConfigHandler):
    def setup(self):
        return

    def user_app(self):
        app = self.context != admin.CONTEXT_NONE and self.appName or "-"
        user = self.context == admin.CONTEXT_APP_AND_USER and self.userName or "nobody"
        return user, app

    def handleList(self, confInfo):
        user, app = self.user_app()
        try:
            url = (
                "{uri}/servicesNS/{user}/{app}/data/indexes"
                "?output_mode=json&search=isInternal=0+disabled=0&count=-1"
                "".format(uri=rest.makeSplunkdUri(), user=user, app=app)
            )
            response, content = rest.simpleRequest(
                url, sessionKey=self.getSessionKey(), method="GET", raiseAllErrors=True
            )
            res = json.loads(content)
            if "entry" in res:
                ent = {"indexes": [entry["name"] for entry in res["entry"]]}
                util.makeConfItem("google_indexes", ent, confInfo)
        except Exception as exc:
            error_ctl.RestHandlerError.ctl(-1, msgx=exc, logLevel=logging.INFO)
        return


def main():
    admin.init(IndexHandler, admin.CONTEXT_APP_AND_USER)
