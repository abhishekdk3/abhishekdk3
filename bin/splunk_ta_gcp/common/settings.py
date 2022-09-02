#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
# flake8: noqa: E402
from future import standard_library

standard_library.install_aliases()
import urllib.parse
from builtins import object

from splunk_ta_gcp import set_log_level
from splunksdc import log as logging
from splunksdc.config import BooleanField, LogLevelField, StanzaParser, StringField

logger = logging.get_module_logger()


class Settings(object):
    @classmethod
    def load(cls, config):
        path = "splunk_ta_google/google_settings"
        content = config.load(path, stanza="global_settings", virtual=True)
        parser = StanzaParser([LogLevelField("log_level")])
        general = parser.parse(content)
        content = config.load(
            path, stanza="proxy_settings", virtual=True, clear_cred=True
        )
        parser = StanzaParser(
            [
                BooleanField("proxy_enabled", default=False, rename="enabled"),
                StringField("proxy_type", rename="scheme", default="http"),
                BooleanField("proxy_rdns", rename="rdns", default=False),
                StringField("proxy_url", rename="host", default="127.0.0.1"),
                StringField("proxy_port", rename="port", default="8080"),
                StringField("proxy_username", rename="username", default=""),
                StringField("proxy_password", rename="password", default=""),
            ]
        )
        proxy = parser.parse(content)
        return cls(general, proxy)

    def __init__(self, general, proxy):
        self._general = general
        self._proxy = proxy

    def setup_log_level(self):
        set_log_level(self._general.log_level)

    def make_proxy_uri(self):
        proxy = self._proxy
        if not proxy.enabled:
            return ""

        scheme = proxy.scheme
        if scheme not in ["http", "socks5", "socks5h", "socks4", "socks4a"]:
            logger.warning("Proxy scheme is invalid", scheme=scheme)
            return ""

        if proxy.rdns:
            if scheme == "socks5":
                scheme = "socks5h"
            elif scheme == "socks4":
                scheme = "socks4a"

        endpoint = "{host}:{port}".format(host=proxy.host, port=proxy.port)
        auth = None
        if proxy.username and len(proxy.username) > 0:
            auth = urllib.parse.quote(proxy.username.encode(), safe="")
            if proxy.password and len(proxy.password) > 0:
                auth += ":"
                auth += urllib.parse.quote(proxy.password.encode(), safe="")

        if auth:
            endpoint = auth + "@" + endpoint

        url = scheme + "://" + endpoint
        return url
