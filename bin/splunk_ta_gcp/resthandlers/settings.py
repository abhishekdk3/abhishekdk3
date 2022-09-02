#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
""" Global settings REST handler
"""

import splunk.admin as admin
from splunktalib.common import util
from splunktaucclib.rest_handler import base, multimodel, normaliser
from splunktaucclib.rest_handler.endpoint import validator

util.remove_http_proxy_env_vars()


class GlobalSettings(base.BaseModel):
    optionalArgs = {
        "log_level",
        "use_kv_store",
        "use_multiprocess",
        "use_hec",
        "base64encoded",
    }
    defaultVals = {
        "log_level": "INFO",
        "use_kv_store": "1",
        "use_multiprocess": "1",
        "use_hec": "0",
        "base64encoded": "1",
    }
    validators = {"log_level": validator.Enum(("DEBUG", "INFO", "ERROR"))}
    normalisers = {
        "use_kv_store": normaliser.Boolean(),
        "use_multiprocess": normaliser.Boolean(),
        "use_hec": normaliser.Boolean(),
        "base64encoded": normaliser.Boolean(),
    }
    outputExtraFields = (
        "eai:acl",
        "acl",
        "eai:attributes",
        "eai:appName",
        "eai:userName",
    )


class ProxySettings(base.BaseModel):
    requiredArgs = {
        "proxy_enabled",
    }
    optionalArgs = {
        "proxy_url",
        "proxy_port",
        "proxy_username",
        "proxy_password",
        "proxy_rdns",
        "proxy_type",
    }
    encryptedArgs = {
        "proxy_password",
    }
    defaultVals = {
        "proxy_enabled": "0",
        "proxy_rdns": "0",
        "proxy_type": "http",
    }
    validators = {
        "proxy_enabled": validator.RequiresIf(
            ("proxy_url", "proxy_port"),
            lambda val, data: val in ("1", "true", "yes"),
        ),
        "proxy_url": validator.AllOf(
            validator.Host(),
            validator.RequiresIf(("proxy_port",)),
        ),
        "proxy_port": validator.AllOf(
            validator.Port(), validator.RequiresIf(("proxy_url",))
        ),
        "proxy_type": validator.Enum(
            ("socks4", "socks5", "http"),
        ),
        "proxy_username": validator.AllOf(
            validator.RequiresIf(("proxy_url", "proxy_password"))
        ),
        "proxy_password": validator.RequiresIf(("proxy_username",)),
    }
    normalisers = {
        "proxy_enabled": normaliser.Boolean(),
        "proxy_rdns": normaliser.Boolean(),
    }
    outputExtraFields = (
        "eai:acl",
        "acl",
        "eai:attributes",
        "eai:appName",
        "eai:userName",
    )


class Settings(multimodel.MultiModel):
    rest_prefix = "google"
    endpoint = "configs/conf-google_cloud_global_settings"
    modelMap = {
        "global_settings": GlobalSettings,
        "proxy_settings": ProxySettings,
    }
    cap4endpoint = ""
    cap4get_cred = ""


def main():
    admin.init(multimodel.ResourceHandler(Settings), admin.CONTEXT_APP_AND_USER)
