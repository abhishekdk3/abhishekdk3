#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import json
from builtins import object

from google.oauth2 import service_account


class CredentialFactory(object):
    def __init__(self, config):
        self._config = config

    def load(self, profile, scopes):
        collection = "splunk_ta_google/google_credentials"
        content = self._config.load(
            collection, stanza=profile, virtual=True, clear_cred=True
        )
        key = content["google_credentials"]
        info = json.loads(key)
        return service_account.Credentials.from_service_account_info(
            info, scopes=scopes
        )
