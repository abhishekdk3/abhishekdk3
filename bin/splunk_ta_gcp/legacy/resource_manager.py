#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import traceback
from builtins import object

import splunk_ta_gcp.legacy.common as gwc

RESOURCE_MGR_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/cloud-platform.read-only",
    "https://www.googleapis.com/auth/cloudplatformprojects",
    "https://www.googleapis.com/auth/cloudplatformprojects.readonly",
]


def get_full_subscription_name(project, subscription):
    """Return a fully qualified subscription name."""
    return gwc.fqrn("subscriptions", project, subscription)


def get_full_topic_name(project, topic):
    """Return a fully qualified topic name."""
    return gwc.fqrn("topics", project, topic)


class GoogleResourceManager(object):
    def __init__(self, logger, config):
        """
        :param: config
        {
            "proxy_url": xxx,
            "proxy_port": xxx,
            "proxy_username": xxx,
            "proxy_password": xxx,
            "proxy_rdns": xxx,
            "proxy_type": xxx,
            "google_credentials": xxx,
            "google_project": xxx,
            "google_subscriptions": xxx,
            "google_topic": xxx,
            "batch_size": xxx,
            "base64encoded": True/False,
        }
        """

        self._config = config
        self._config["scopes"] = RESOURCE_MGR_SCOPES
        self._config["service_name"] = "cloudresourcemanager"
        self._config["version"] = "v1beta1"
        self._logger = logger
        self._client = gwc.create_google_client(self._config)

    def projects(self):
        """
        return a list of all projects
        {
        "projectId": xx,
        "createTime": "2013-08-23T11:34:06.523Z",
        "projectNumber": xx,
        "name": xx,
        "lifecycleState": "ACTIVE"
        }
        """

        try:
            projects = list()
            request = self._client.projects().list()
            while request:
                response = request.execute(num_retries=3)
                projects.extend(response["projects"])
                request = self._client.projects().list_next(
                    previous_request=request, previous_response=response
                )

        except Exception:
            self._logger.error(
                "Failed to list Google projects, error=%s", traceback.format_exc()
            )
            raise

        return projects
