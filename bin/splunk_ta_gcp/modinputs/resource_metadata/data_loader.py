#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import socket
import time
import traceback
from builtins import object, range

import splunksdc.log as logging
from googleapiclient import discovery
from oauth2client.service_account import ServiceAccountCredentials

from . import consts as grc

logger = logging.get_module_logger()


def get_supported_resource_apis():
    """
    Returns Dictionary of supported APIs
    """

    endpoints = [
        "instances",
        "acceleratorTypes",
        "autoscalers",
        "diskTypes",
        "disks",
        "instanceGroupManagers",
        "instanceGroups",
        "machineTypes",
        "networkEndpointGroups",
        "nodeGroups",
        "nodeTypes",
        "reservations",
        "targetInstances",
        "zoneOperations",
    ]
    stored_values = [
        "instances",
        "accelerator_types",
        "autoscalers",
        "disk_types",
        "disks",
        "instance_group_managers",
        "instance_groups",
        "machine_types",
        "network_endpoint_groups",
        "node_groups",
        "node_types",
        "reservations",
        "target_instance",
        "operation_resources",
    ]
    return {stored_values[i]: endpoints[i] for i in range(len(endpoints))}


class ResourceDataLoader(object):
    """
    Data Loader for Resource Metadata Input
    """

    def __init__(self, task_config):
        """
        :task_config: dict object
        {
            "polling_interval": 30,
            "google_api": "ec2_instances" etc,
            "google_zone": "us_east_A" etc,
            "source": xxx,
            "sourcetype": yyy,
            "index": zzz,
        }
        """

        self._task_config = task_config
        self._supported_desc_apis = get_supported_resource_apis()
        self._api = self._supported_desc_apis.get(self._task_config[grc.api], None)
        self._zone = self._task_config[grc.zone]
        self._project = self._task_config["google_project"]
        self._event_writer = None
        self._host = socket.gethostname()
        creds = ServiceAccountCredentials.from_json_keyfile_dict(
            self._task_config["google_credentials"]
        )
        self._service = discovery.build("compute", "v1", credentials=creds)
        self._stopped = False
        if self._api is None or self._zone is None:
            logger.error(
                "Unsupported api or Zone.",
                api=self._task_config[grc.api],
                zone=self._task_config[grc.zone],
                ErrorCode="ConfigurationError",
                ErrorDetail="Service is unsupported.",
                datainput=self._task_config[grc.source],
            )

    def __call__(self):
        with logging.LogContext(datainput=self._task_config[grc.source]):
            self.index_data()

    def index_data(self):
        """
        Ingests Data to Splunk
        """
        if self._api is not None:
            logger.info(
                "Start collecting resource for api=%s, zone=%s", self._api, self._zone
            )

            if self._event_writer is None:
                self._event_writer = self._task_config["event_writer"]
            try:
                self._do_index_data()
            except Exception:
                logger.exception("Failed to collect resource data for %s.", self._api)
                logger.exception(traceback.format_exc())
            logger.info(
                "End of collecting resource for api=%s, zone=%s", self._api, self._zone
            )
        else:
            logger.warning(
                self._task_config[grc.api]
                + " seems to be invalid, skipping this input."
            )

    def _do_index_data(self):
        if self._api is None or self._zone is None:
            return

        task = self._task_config
        results = self.fetch_results(self._api, self._zone)
        events = []
        for result in results:
            result["Project"] = (task["google_project"],)
            result["Credentials"] = task["name"]

            event = self._event_writer.create_event(
                index=task[grc.index],
                source=task[grc.source],
                host=self._host,
                sourcetype=task[grc.sourcetype],
                time=time.time(),
                unbroken=False,
                done=False,
                events=result,
            )
            events.append(event)
        logger.info("Send data for indexing.", action="index", records=len(events))

        self._event_writer.write_events(events, retry=10)

    def fetch_results(self, api, zone):
        """
        Gets resource metadata for specified Google Cloud API
        Arguement : "api"
        Type : String
        Arguement : "zone"
        Type : String
        """

        logger.debug("Starting to fetch data for " + api)

        # Assiging the API method of discovery.Resource Object to method_to_call
        method_to_call = getattr(self._service, api)()

        # Calling list of method_to_call
        request = method_to_call.list(project=self._project, zone=zone)
        result = []
        while request is not None:
            response = request.execute()
            try:
                for instance in response["items"]:
                    result.append(instance)
                request = method_to_call.list_next(
                    previous_request=request, previous_response=response
                )
            except KeyError:
                logger.info("Found no items in " + api)
                request = method_to_call.list_next(
                    previous_request=request, previous_response=response
                )
            except Exception:
                logger.error(traceback.format_exc())

        logger.debug("Fetching data for " + api + " completed.")
        return result

    def get_interval(self):
        """
        returns intreval from config.
        """

        return self._task_config[grc.interval]

    def get_props(self):
        """
        returns config.
        """

        return self._task_config

    def stop(self):
        """
        Sets _stopped flag to True
        """
        self._stopped = True
        logger.info("Stopping GoogleCloudResourceMetadataDataLoader")
