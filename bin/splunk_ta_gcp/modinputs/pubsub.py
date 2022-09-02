#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
# flake8: noqa: E402
from future import standard_library

standard_library.install_aliases()
import base64
import itertools
import json
import os
import platform
import queue
import re
import threading
import time
from builtins import object, range
from collections import OrderedDict
from datetime import datetime

from google.auth.transport.requests import AuthorizedSession
from requests.exceptions import RequestException
from splunk_ta_gcp.common.credentials import CredentialFactory
from splunk_ta_gcp.common.settings import Settings
from splunksdc import logging
from splunksdc.collector import SimpleCollectorV1
from splunksdc.config import StanzaParser, StringField
from splunksdc.utils import LogExceptions, LogWith

logger = logging.get_module_logger()


class RestParcel(object):
    def __init__(self, content, created, ttl, renew, ack, now):
        self._messages = content.get("receivedMessages", [])
        self._created = created
        self._ttl = ttl
        self._renew = renew
        self._ack = ack
        self._now = now

    def render(self):
        lines = itertools.chain(
            [self._render(item["message"]) for item in self._messages], ""
        )
        return "\n".join(lines)

    def ack(self):
        tokens = self._get_ack_tokens()
        self._ack(tokens)

    def renew(self, seconds):
        now = self._now()
        tokens = self._get_ack_tokens()
        self._renew(tokens, seconds)
        self._created = now
        self._ttl = seconds

    def _get_ack_tokens(self):
        return [item["ackId"] for item in self._messages]

    @property
    def ttl(self):
        return self._ttl

    def has_elapsed(self):
        return self._now() - self._created

    def __bool__(self):
        return bool(self._messages)

    _datetime_format = re.compile(
        r"(?P<Y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})T(?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})(?P<f>\.\d+)?Z"
    )

    @classmethod
    def _render(cls, message):

        programs = [
            cls._extract_publish_time,
            cls._extract_payload,
            cls._extract_attributes,
        ]
        event = OrderedDict()
        for extractor in programs:
            try:

                key, value = extractor(message)
                event[key] = value
                if isinstance(event[key], bytes):
                    event[key] = event[key].decode("utf-8")
            except KeyError:
                continue
        event = dict(event)
        return json.dumps(event)

    @classmethod
    def _extract_publish_time(cls, message):
        ptime = message["publishTime"]
        match = cls._datetime_format.match(ptime)
        time_parts = match.groups()
        fraction = time_parts[-1] or ".0"
        fraction = float(fraction)
        parts = [int(_) for _ in time_parts[:-1]]
        elapsed = datetime(*parts) - datetime.utcfromtimestamp(0)
        seconds = int(elapsed.total_seconds())
        return "publish_time", seconds + fraction

    @classmethod
    def _extract_payload(cls, message):
        data = message["data"]

        try:
            data = base64.b64decode(data)
        except TypeError:
            logger.warning("base64 decoding failed.")

        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            logger.debug("payload is not a json string.")

        return "data", data

    @classmethod
    def _extract_attributes(cls, message):
        return "attributes", message["attributes"]


class RESTAgent(object):
    def __init__(self, subscription, session):
        self._subscription = subscription
        self._session = session
        self._ttl = 0
        self._clock = time.time

    def pull(self):
        if not self._ttl:
            self._ttl = self._get_acknowledge_deadline()
        endpoint = self._make_endpoint(self._subscription, "pull")
        params = {
            "returnImmediately": False,
            "maxMessages": 1024,
        }
        response = self._session.post(endpoint, json=params)
        now = self.now()
        response.raise_for_status()
        content = response.json()
        return RestParcel(content, now, self._ttl, self.renew, self.ack, self.now)

    def ack(self, tokens):
        endpoint = self._make_endpoint(self._subscription, "acknowledge")
        body = {"ackIds": tokens}
        response = self._session.post(endpoint, json=body)
        response.raise_for_status()
        return

    def renew(self, tokens, seconds):
        endpoint = self._make_endpoint(self._subscription, "modifyAckDeadline")
        body = {"ackIds": tokens, "ackDeadlineSeconds": seconds}
        response = self._session.post(endpoint, json=body)
        response.raise_for_status()
        return

    def now(self):
        return self._clock()

    def _get_acknowledge_deadline(self):
        endpoint = self._make_endpoint(self._subscription)
        response = self._session.get(endpoint)
        response.raise_for_status()
        content = response.json()
        return content.get("ackDeadlineSeconds", 10)

    @property
    def subscription(self):
        return self._subscription

    @staticmethod
    def _make_endpoint(resource, action=None):
        api = "https://pubsub.googleapis.com/v1"
        action = "" if not action else ":" + action
        return "{}/{}{}".format(api, resource, action)


class PubSubConsumer(object):
    def __init__(self, agent, send_data):
        self._agent = agent
        self._send_data = send_data

    def run(self):
        agent = self._agent
        parcel = agent.pull()
        if not parcel:
            logger.info(
                "No message available in subscription.",
            )
            return
        if not self._try_send_data(parcel):
            return
        parcel.ack()
        lapse = parcel.has_elapsed()
        ttl = parcel.ttl
        if lapse >= ttl:
            logger.warning(
                "Data duplication may occurred due to acknowledging too late.",
                lapse=lapse,
                ttl=ttl,
            )
        return

    def _try_send_data(self, parcel):
        send_data = self._send_data
        agent = self._agent
        subscription = agent.subscription
        data = parcel.render()
        lapse = parcel.has_elapsed()
        ttl = parcel.ttl
        timeout = ttl - lapse
        # sending data to splunk is time consuming. reserve 3 seconds for it.
        if timeout <= 3:
            logger.error(
                "Not enough time to send data for indexing.", lapse=lapse, ttl=ttl
            )
            return False

        timeout = 3
        for _ in range(2):
            try:
                return send_data(data, source=subscription, timeout=timeout)
            except queue.Full:
                # server is busy, lease messages with max timeout and try again
                parcel.renew(600)
                timeout = parcel.ttl
                logger.warning("Modify messages acknowledge deadline.", timeout=timeout)
                continue

        logger.error(
            "Messages were skipped for indexing due to server too busy.",
            timeout=timeout,
        )
        return False


class AsyncWrite(object):
    def __init__(self, data, source):
        self._done = threading.Event()
        self._result = None
        self._data = data
        self._source = source

    def result(self):
        self._done.wait()
        return self._result

    def commit(self, write_fileobj):
        succeed = write_fileobj(self._data, source=self._source)
        self._set_result(succeed)

    def cancel(self):
        self._set_result(False)

    def _set_result(self, value):
        self._result = value
        self._done.set()


class PubSubConsumerGroup(object):
    def __init__(self, write_fileobj, check_aborting_signal):
        self._write_fileobj = write_fileobj
        self._check_aborting_signal = check_aborting_signal
        self._stopped = False
        self._threads = list()
        self._agents = list()
        self._queue = queue.Queue(2)
        self._prefix = logging.ThreadLocalLoggingStack.top()

    def run(self):
        self._begin()
        while not self._should_exit():
            self._process_requests()
        self._end()
        return 0

    def add(self, agent):
        self._agents.append(agent)

    def _begin(self):
        self._stopped = False
        self._threads = list()
        for agent in self._agents:
            thread = threading.Thread(target=self._run_agent, args=(agent,))
            thread.daemon = True
            thread.start()
            self._threads.append(thread)

    def _end(self):
        self._stopped = True
        for _ in self._threads:
            self._cancel_requests()

        for thread in self._threads:
            thread.join(5)

    def _should_exit(self):
        if self._check_aborting_signal():
            return True
        if self._is_idle():
            return True
        if self._times_up():
            return True
        return False

    def _is_idle(self):
        for thread in self._threads:
            thread.join(0)
            if thread.is_alive():
                return False
        return True

    def _times_up(self):
        return False

    @property
    def prefix(self):
        return self._prefix

    @LogWith(prefix=prefix)
    def _run_agent(self, agent):
        subscription = agent.subscription
        send_data = self._write_indirectly
        consumer = PubSubConsumer(agent, send_data)
        with logging.LogContext(subscription=subscription):
            return self._run_consumer(consumer)

    def _run_consumer(self, consumer):
        wait = 0
        is_aborted = self._is_stopped
        while not is_aborted():
            if wait > 0:
                time.sleep(1)
                wait -= 1
                continue
            try:
                consumer.run()
            except RequestException:
                wait = 60
                logger.exception("An error occurred when pulling message.")
        return 0

    def _foreach_request(self, callback):
        count = 8
        try:
            while count > 0:
                op = self._queue.get(timeout=2)
                callback(op)
                count -= 1
        except queue.Empty:
            logger.debug("No more pending data.")

    def _process_requests(self):
        self._foreach_request(lambda op: op.commit(self._write_fileobj))

    def _cancel_requests(self):
        self._foreach_request(lambda op: op.cancel())

    def _write_indirectly(self, data, source, timeout):
        if self._stopped:
            return False
        async_write = AsyncWrite(data, source)
        self._queue.put(async_write, timeout=timeout)
        return async_write.result()

    def _is_stopped(self):
        return self._stopped


class PubSubHandler(object):
    def __init__(self, app, config, settings, credentials, event_writer):
        self._app = app
        self._config = config
        self._settings = settings
        self._credentials = credentials
        self._event_writer = event_writer

    def _check_aborting_signal(self):
        # Do not check configuration changes due to rest handler consumes too much resource.
        # if self._config.has_expired():
        #   return True
        return self._app.is_aborted()

    def _write_directly(self, data, source, timeout):
        self._event_writer.write_fileobj(data, source=source)
        return True

    def run(self, subscriptions):
        if len(subscriptions) == 1:
            return self._run_consumer(subscriptions[0])
        return self._run_consumer_group(subscriptions)

    def _run_consumer(self, subscription):
        check_aborting_signal = self._check_aborting_signal
        write_directly = self._write_directly
        agent = self._create_subscriber(subscription)
        consumer = PubSubConsumer(agent, write_directly)
        try:
            while not check_aborting_signal():
                consumer.run()
        except RequestException:
            logger.exception(
                "An error occurred when pulling subscription.",
                subscription=subscription,
            )
        return 0

    def _run_consumer_group(self, subscriptions):
        write_fileobj = self._event_writer.write_fileobj
        check_aborting_signal = self._check_aborting_signal
        group = PubSubConsumerGroup(write_fileobj, check_aborting_signal)
        for subscription in subscriptions:
            agent = self._create_subscriber(subscription)
            group.add(agent)
        return group.run()

    def remove_http_proxy_env_vars(self):
        for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
            if k in os.environ:
                del os.environ[k]
            elif k.upper() in os.environ:
                del os.environ[k.upper()]

    def _create_subscriber(self, subscription):
        session = AuthorizedSession(self._credentials)
        proxy = self._settings.make_proxy_uri()
        if proxy:
            # Removing proxy variables from environment to resolve the ADDON-23986 issue
            self.remove_http_proxy_env_vars()
            session.proxies = {"http": proxy, "https": proxy}
            # Adding proxies information to _auth_request object which is part of session object. This code is added since
            # pubsub inputs failed to collect data when proxy is configured on the instance.
            session._auth_request.session.proxies = {"http": proxy, "https": proxy}
        return RESTAgent(subscription, session)


class PubSubInput(object):
    def __init__(self, stanza):
        self._kind = stanza.kind
        self._name = stanza.name
        self._args = stanza.content
        self._start_time = int(time.time())

    @property
    def name(self):
        return self._name

    @property
    def start_time(self):
        return self._start_time

    def _extract_arguments(self, parser):
        return parser.parse(self._args)

    def _create_event_writer(self, app):
        stanza = self._kind + "://" + self._name
        parser = StanzaParser(
            [
                StringField("index"),
                StringField("host"),
                StringField("stanza", fillempty=stanza),
                StringField("sourcetype", default="google:gcp:pubsub:message"),
            ]
        )
        metadata = self._extract_arguments(parser)
        try:
            if metadata.host == "$decideOnStartup":
                metadata.host = platform.node()
        except:
            pass
        return app.create_event_writer(None, **vars(metadata))

    def _create_subscriptions(self):
        parser = StanzaParser(
            [
                StringField("google_project", required=True),
                StringField("google_subscriptions", required=True),
            ]
        )
        args = self._extract_arguments(parser)
        project = args.google_project
        subscriptions = args.google_subscriptions
        if "," in subscriptions:
            subscriptions = subscriptions.split(",")
            subscriptions = [item.strip() for item in subscriptions]
        else:
            subscriptions = [subscriptions]

        template = "projects/{}/subscriptions/{}"
        return [template.format(project, name) for name in subscriptions]

    def _create_credentials(self, config):
        scopes = ["https://www.googleapis.com/auth/pubsub"]
        parser = StanzaParser(
            [StringField("google_credentials_name", rename="profile")]
        )
        args = self._extract_arguments(parser)
        factory = CredentialFactory(config)
        return factory.load(args.profile, scopes)

    @LogWith(datainput=name, start_time=start_time)
    @LogExceptions(
        logger, "Data input was interrupted by an unhandled exception.", lambda e: -1
    )
    def run(self, app, config):
        settings = Settings.load(config)
        settings.setup_log_level()
        event_writer = self._create_event_writer(app)
        credentials = self._create_credentials(config)
        subscriptions = self._create_subscriptions()
        handler = PubSubHandler(app, config, settings, credentials, event_writer)
        return handler.run(subscriptions)


def modular_input_run(app, config):
    inputs = app.inputs()
    datainput = PubSubInput(inputs[0])
    return datainput.run(app, config)


def main():
    arguments = {
        "google_credentials_name": {"title": "The name of Google service account"},
        "google_project": {"title": "The Google project ID"},
        "google_subscriptions": {"title": "List of subscriptions' names"},
    }
    SimpleCollectorV1.main(
        modular_input_run,
        title="Google Pub/Sub Subscription",
        use_single_instance=False,
        arguments=arguments,
    )
