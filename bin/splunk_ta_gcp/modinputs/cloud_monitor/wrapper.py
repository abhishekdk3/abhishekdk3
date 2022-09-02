#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import traceback
from builtins import object

import splunk_ta_gcp.legacy.common as gwc
from googleapiclient.errors import HttpError

MONITOR_SCOPES = [
    "https://www.googleapis.com/auth/monitoring",
    "https://www.googleapis.com/auth/cloud-platform",
]


def get_pagination_results(service, req, key):
    all_results = []
    if req is None:
        return all_results

    result = req.execute(num_retries=3)
    if result and result.get(key):
        all_results.extend(result[key])

    if "nextPageToken" in result:
        while 1:
            req = service.list_next(req, result)
            if not req:
                break

            result = req.execute(num_retries=3)
            if result and result.get(key):
                all_results.extend(result[key])
            else:
                break

    return all_results


class GoogleCloudMonitor(object):
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
        }
        """

        self._config = config
        self._config["scopes"] = MONITOR_SCOPES
        self._config["service_name"] = "monitoring"
        self._config["version"] = "v3"
        self._logger = logger
        self._client = gwc.create_google_client(self._config)

    def list_metrics(self, params):
        """
        :params: dict like object
        {
        "google_project": xxx,
        "google_metrics": xxx,
        "oldest": "2016-01-16T00:00:00-00:00",
        "youngest": "2016-02-16T00:00:00-00:00",
        ...
        }
        return:
        """

        try:
            project_name = params["google_project"]
            metric = params["google_metrics"]
            resource = self._client.projects().timeSeries()
            request = resource.list(
                name="projects/" + project_name,
                filter='metric.type="{}"'.format(metric),
                interval_startTime=params["oldest"],
                interval_endTime=params["youngest"],
            )
            return get_pagination_results(resource, request, "timeSeries")
        except Exception:
            self._logger.error(
                "Failed to list Google metric for project=%s, metric=%s, " "error=%s",
                params["google_project"],
                params["google_metrics"],
                traceback.format_exc(),
            )
            raise

    def write_metrics(self, metrics):
        pass

    def metric_descriptors(self, project_name):
        """
        return a list of metric_descriptor
        {
        "name": "appengine.googleapis.com/http/server/dos_intercept_count",
        "project": "1002621264351",
        "labels": [
            {
                 "key": "appengine.googleapis.com/module"
            },
            {
                 "key": "appengine.googleapis.com/version"
            },
            {
                 "key": "cloud.googleapis.com/location"
            },
            {
                 "key": "cloud.googleapis.com/service"
            }
        ],
        "typeDescriptor": {
            "metricType": "delta",
            "valueType": "int64"
        },
        "description": "Delta count of ... to prevent DoS attacks.",
        }
        """

        try:
            resource = self._client.projects().metricDescriptors()
            request = resource.list(name="projects/" + project_name)
            return get_pagination_results(resource, request, "metricDescriptors")
        except HttpError as e:
            if e.resp.status == 403:
                self._logger.error(
                    "Daily limit exceeded. Try again later. " "project=%s",
                    project_name,
                )
                raise ValueError("Daily limit exceeded. Try again later.")
            raise
        except Exception:
            self._logger.error(
                "Failed to list Google metric descriptors for " "project=%s, error=%s",
                project_name,
                traceback.format_exc(),
            )
            raise


if __name__ == "__main__":  # pragma: no cover
    import logging
    import os
    import pprint

    logger = logging.getLogger("google")
    ch = logging.StreamHandler()
    logger.addHandler(ch)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "Splunk-GCP-32a3be8f2f0d.json"
    config = {
        "google_project": "splunk-gcp",
        "google_metrics": "pubsub.googleapis.com/topic/send_message_operation_count",
        "oldest": "2016-07-01T00:00:00Z",
        "youngest": "2016-07-20T00:00:00Z",
    }

    gcm = GoogleCloudMonitor(logger, config)
    descriptors = gcm.metric_descriptors(config["google_project"])
    pprint.pprint(len(descriptors))
    pprint.pprint(descriptors)

    metrics = gcm.list_metrics(config)
    pprint.pprint(metrics)
