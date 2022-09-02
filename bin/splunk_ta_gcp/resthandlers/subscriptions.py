#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import logging
import traceback
from builtins import object

import splunk.admin as admin
import splunk.clilib.cli_common as scc
import splunk_ta_gcp.legacy.common as gwc
import splunk_ta_gcp.legacy.config as gconf
import splunk_ta_gcp.legacy.consts as ggc
import splunktalib.common.pattern as scp
import splunktalib.common.util as scutil

logger = logging.getLogger()


PUBSUB_SCOPES = ["https://www.googleapis.com/auth/pubsub"]


# def get_full_subscription_name(project, subscription):
#     """Return a fully qualified subscription name."""
#     return gwc.fqrn("subscriptions", project, subscription)


# def get_full_topic_name(project, topic):
#     """Return a fully qualified topic name."""
#     return gwc.fqrn('topics', project, topic)


class GooglePubSub(object):
    def __init__(self, config):
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
        self._config["scopes"] = PUBSUB_SCOPES
        self._config["service_name"] = "pubsub"
        self._config["version"] = "v1"
        self._logger = logger
        self._client = gwc.create_google_client(self._config)
        self._base64encoded = scutil.is_true(self._config.get("base64encoded"))

    # def pull_messages(self):
    #     """Pull messages from a given subscription."""

    #     subscription = get_full_subscription_name(
    #         self._config["google_project"],
    #         self._config["google_subscriptions"])

    #     body = {
    #         "returnImmediately": False,
    #         "maxMessages": self._config.get("batch_size", 100)
    #     }

    #     while 1:
    #         try:
    #             resp = self._client.projects().subscriptions().pull(
    #                 subscription=subscription, body=body).execute(
    #                 num_retries=3)
    #         except ssl.SSLError as e:
    #             if "timed out" in e.message:
    #                 yield []
    #                 continue
    #         except Exception:
    #             self._logger.error(
    #                 "Failed to pull messages from subscription=%s, error=%s",
    #                 subscription, traceback.format_exc())
    #             time.sleep(2)
    #             continue

    #         messages = resp.get("receivedMessages")
    #         if not messages:
    #             yield []

    #         if self._base64encoded:
    #             for message in messages:
    #                 msg = message.get("message")
    #                 if msg and msg.get("data"):
    #                     try:
    #                         msg["data"] = base64.b64decode(str(msg["data"]))
    #                     except TypeError:
    #                         logger.error(
    #                             "Invalid base64 event=%s", msg["data"])

    #         yield messages

    # def ack_messages(self, messages):
    #     if not messages:
    #         return

    #     ack_ids = []
    #     for message in messages:
    #         ack_ids.append(message.get("ackId"))

    #     ack_body = {"ackIds": ack_ids}
    #     subscription = get_full_subscription_name(
    #         self._config["google_project"],
    #         self._config["google_subscriptions"])

    #     self._client.projects().subscriptions().acknowledge(
    #         subscription=subscription, body=ack_body).execute(num_retries=3)

    # def publish_messages(self, messages):
    #     topic = get_full_topic_name(
    #         self._config["google_project"], self._config["google_topic"])
    #     messages = [{"data": base64.b64encode(msg)} for msg in messages]
    #     body = {"messages": messages}
    #     return self._client.projects().topics().publish(
    #         topic=topic, body=body).execute(num_retries=3)

    def _do_list(self, queryer, key):
        project_name = self._config["google_project"]
        project = "projects/{project}".format(project=project_name)
        result = None
        try:
            result = queryer.list(project=project, pageSize=1000).execute(num_retries=3)
        except Exception:
            self._logger.error(
                "Failed to list Google %s for project=%s, error=%s",
                key,
                project_name,
                traceback.format_exc(),
            )

        if result:
            return result[key]
        else:
            return []

    def subscriptions(self):
        """
        return a list of subscriptions
        {
        "topic": "projects/<project_id>/topics/<topic_name>",
        "ackDeadlineSeconds": 10,
        "pushConfig": {},
        "name": "projects/<project_id>/subscriptions/<subscript_name>"
        }
        """

        return self._do_list(self._client.projects().subscriptions(), "subscriptions")

    # def create_subscription(self):
    #     topic = get_full_topic_name(
    #         self._config["google_project"], self._config["google_topic"])
    #     subscription = get_full_subscription_name(
    #         self._config["google_project"],
    #         self._config["google_subscriptions"])

    #     body = {
    #         "topic": topic
    #     }

    #     try:
    #         self._client.projects().subscriptions().create(
    #             name=subscription, body=body).execute(num_retries=3)
    #     except Exception:
    #         self._logger.error(
    #             "Failed to create Google subscription=%s for project=%s, "
    #             "error=%s", self._config["google_subscriptions"],
    #             self._config["google_project"], traceback.format_exc())

    # def topics(self):
    #     """
    #     return a list of topics
    #     {
    #     "name": "projects/<project_id>/topics/<topic_name>"
    #     }
    #     """

    #     return self._do_list(
    #         self._client.projects().topics(), "topics")

    # def create_topic(self):
    #     topic = get_full_topic_name(self._config["google_project"],
    #                                 self._config["google_topic"])
    #     body = {
    #         "name": topic
    #     }

    #     try:
    #         self._client.projects().topics().create(
    #             name=topic, body=body).execute(num_retries=3)
    #     except Exception:
    #         self._logger.error(
    #             "Failed to create Google topic=%s for project=%s, error=%s",
    #             self._config["google_topic"], self._config["google_project"],
    #             traceback.format_exc())


class GoogleSubscriptions(admin.MConfigHandler):
    valid_params = [ggc.google_credentials_name, ggc.google_project]

    def setup(self):
        for param in self.valid_params:
            self.supportedArgs.addOptArg(param)

    @scp.catch_all(logger)
    def handleList(self, conf_info):
        logger.info("start listing google subscriptions")
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
        ps = GooglePubSub(config)
        subscriptions = [sub["name"].split("/")[-1] for sub in ps.subscriptions()]
        for subscription in subscriptions:
            conf_info[subscription].append("subscriptions", subscription)
        logger.info("end of listing google subscriptions")


def main():
    admin.init(GoogleSubscriptions, admin.CONTEXT_NONE)
