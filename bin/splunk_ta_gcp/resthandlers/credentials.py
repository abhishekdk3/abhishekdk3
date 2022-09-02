#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import json

import splunk.admin as admin
from six import string_types
from splunk.rest import makeSplunkdUri
from splunktalib.common import util
from splunktalib.rest import splunkd_request
from splunktaucclib.rest_handler import base
from splunktaucclib.rest_handler.endpoint import validator
from splunktaucclib.rest_handler.error_ctl import RestHandlerError as RH_Err

util.remove_http_proxy_env_vars()


class GoogleCredentials(base.BaseModel):
    """REST Endpoint of Server in Splunk Add-on UI Framework."""

    rest_prefix = "google"
    endpoint = "configs/conf-google_cloud_credentials"
    requiredArgs = {"google_credentials"}
    encryptedArgs = {"google_credentials"}
    validators = {"google_credentials": validator.JsonString()}
    outputExtraFields = (
        "eai:acl",
        "acl",
        "eai:attributes",
        "eai:appName",
        "eai:userName",
    )
    cap4endpoint = ""
    cap4get_cred = ""


class GoogleCredentialsHandler(base.BaseRestHandler):

    _depended_endpoints = [
        {
            "endpoint": "splunk_ta_google/google_inputs_billing",
            "description": "Billing Input",
            "fields": ["google_credentials_name"],
        },
        {
            "endpoint": "splunk_ta_google/google_inputs_monitoring",
            "description": "Monitoring Input",
            "fields": ["google_credentials_name"],
        },
        {
            "endpoint": "splunk_ta_google/google_inputs_pubsub",
            "description": "Pub/Sub Input",
            "fields": ["google_credentials_name"],
        },
        {
            "endpoint": "splunk_ta_google/google_inputs_resource_metadata",
            "description": "Resource Metadata",
            "fields": ["google_credentials_name"],
        },
        {
            "endpoint": "splunk_ta_google/google_inputs_storage_buckets",
            "description": "Cloud Bucket Input",
            "fields": ["google_credentials_name"],
        },
    ]

    def make_endpoint_url(self, endpoint):
        user, app = self.user_app()
        return (
            makeSplunkdUri().strip("/")
            + "/servicesNS/"
            + user
            + "/"
            + app
            + "/"
            + endpoint.strip("/")
        )

    def check_entries(self, endpoint, entries):
        for ent in entries:
            name, ent = ent["name"], ent["content"]
            for field in endpoint["fields"]:
                val = ent.get(field)
                if isinstance(val, string_types):
                    val = [val]
                if self.callerArgs.id in val:
                    RH_Err.ctl(
                        400,
                        'It is still used in %s "%s"'
                        "" % (endpoint["description"], name),
                    )

    def handleRemove(self, confInfo):
        try:
            for ep in self._depended_endpoints:
                url = self.make_endpoint_url(ep.get("endpoint"))
                resp, cont = splunkd_request(
                    url, self.getSessionKey(), data={"output_mode": "json"}
                )
                if resp.status not in (200, "200"):
                    raise Exception(cont)
                res = json.loads(cont)
                self.check_entries(ep, res["entry"])
        except Exception as exc:
            RH_Err.ctl(1105, exc)
        super(GoogleCredentialsHandler, self).handleRemove(confInfo)


def main():
    admin.init(
        base.ResourceHandler(
            GoogleCredentials,
            handler=GoogleCredentialsHandler,
        ),
        admin.CONTEXT_APP_AND_USER,
    )
