#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
from __future__ import absolute_import

import logging

from splunk_ta_gcp.resthandlers.inputs import custom_validator
from splunktaucclib.rest_handler import admin_external, util
from splunktaucclib.rest_handler.admin_external import AdminExternalHandler
from splunktaucclib.rest_handler.endpoint import DataInputModel, RestModel, field

util.remove_http_proxy_env_vars()


fields = [
    field.RestField(
        "google_credentials_name",
        required=True,
        encrypted=False,
        default=None,
        validator=custom_validator.StringValidator(min_len=1, max_len=4096),
    ),
    field.RestField(
        "google_project",
        required=True,
        encrypted=False,
        default=None,
        validator=custom_validator.StringValidator(min_len=1, max_len=4096),
    ),
    field.RestField(
        "google_subscriptions",
        required=True,
        encrypted=False,
        default=None,
        validator=custom_validator.StringValidator(min_len=1, max_len=4096),
    ),
    field.RestField(
        "index",
        required=True,
        encrypted=False,
        default="default",
        validator=custom_validator.StringValidator(min_len=1, max_len=4096),
    ),
    field.RestField("disabled", required=False, validator=None),
]
model = RestModel(fields, name=None)


endpoint = DataInputModel(
    "google_cloud_pubsub",
    model,
)


def main():
    logging.getLogger().addHandler(logging.NullHandler())
    admin_external.handle(
        endpoint,
        handler=AdminExternalHandler,
    )
