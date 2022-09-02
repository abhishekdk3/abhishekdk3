#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
# flake8: noqa: E402
from future import standard_library

standard_library.install_aliases()
import base64
import json
import tempfile
from builtins import chr, object, zip

import google_cloud_bootstrap
import httplib2
import httplib2shim
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from urllib.parse import unquote, urlparse

from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build as build_service_client
from googleapiclient.errors import Error as GoogleAPIClientError
from googleapiclient.http import MediaIoBaseDownload
from httplib2.socks import (
    PROXY_TYPE_HTTP,
    PROXY_TYPE_SOCKS4,
    PROXY_TYPE_SOCKS5,
    ProxyError,
)
from splunk_ta_gcp.common.credentials import CredentialFactory
from splunk_ta_gcp.common.settings import Settings
from splunksdc import logging
from splunksdc.collector import SimpleCollectorV1
from splunksdc.config import (
    BooleanField,
    DateTimeField,
    IntegerField,
    StanzaParser,
    StringField,
)
from splunksdc.utils import LogExceptions

logger = logging.get_module_logger()


class DiscoverServiceError(Exception):
    def __init__(self, exception, service, version):
        self.exception = exception
        self.service = service
        self.version = version


class ListBucketError(Exception):
    def __init__(self, exception, bucket_name, prefix, last_file):
        self.exception = exception
        self.bucket_name = bucket_name
        self.prefix = prefix
        self.last_file = last_file


class BillingDataInputs(object):
    def __init__(self, app, config):
        self._app = app
        self._config = config

    def load(self):
        workspace = self._app.workspace()
        content = self._config.load("google_cloud_billing_inputs")
        for name, fields in list(content.items()):
            parser = StanzaParser(
                [
                    BooleanField(
                        "disabled", default=False, reverse=True, rename="enabled"
                    ),
                    StringField("bucket_name", required=True),
                    StringField("report_prefix", required=True),
                    StringField(
                        "google_credentials_name", required=True, rename="profile"
                    ),
                    StringField("sourcetype", default="google:gcp:billing:report"),
                    DateTimeField("ingestion_start", default="1970-01-01"),
                    StringField("temp_file_folder", default=workspace),
                    IntegerField("polling_interval", default=300, rename="interval"),
                    StringField("index"),
                ]
            )
            params = parser.parse(fields)
            if params.enabled:
                yield name, params

    def __iter__(self):
        return self.load()


class BillingIngestionCheckpoint(object):
    def __init__(self, store):
        self._store = store

    def has_pending_reports(self):
        for _ in self._store.prefix("/pending/"):
            return True
        return False

    def pending_reports(self, keys):
        for key in keys:
            item = "/pending/" + key
            self._store.set(item, None)

    def query_pending_reports(self):
        return [item[9:] for item in self._store.prefix("/pending/")]

    def remove_pending_report(self, key):
        item = "/pending/" + key
        self._store.delete(item)

    def query_marker(self):
        for item in self._store.prefix("/last/", reverse=True):
            return item[6:]
        return None

    def update_marker(self, key):
        if key is None:
            return
        self._store.set("/last/" + key, None)

        markers = [item for item in self._store.prefix("/last/")]
        garbage = markers[0:-1]
        for item in garbage:
            self._store.delete(item)


class BillingReportsHandler(object):
    def __init__(
        self,
        checkpoint,
        event_writer,
        storage,
        bucket_name,
        report_prefix,
        ingestion_start,
        temp_folder,
    ):
        self._ingestion_start = ingestion_start
        self._report_prefix = report_prefix
        self._bucket_name = bucket_name
        self._checkpoint = BillingIngestionCheckpoint(checkpoint)
        self._service = storage
        self._temp_file_folder = temp_folder
        self._event_writer = event_writer

    def run(self):
        try:
            reports = self._find_reports()
            if not reports:
                logger.info("reports not found.")
            for key in reports:
                self._process(key)
        except DiscoverServiceError as e:
            logger.error(
                "discover service failed",
                service=e.service,
                version=e.version,
                exception=e.exception,
            )
        except ListBucketError as e:
            logger.error(
                "list bucket failed",
                bucket_name=e.bucket_name,
                prefix=e.prefix,
                last_file=e.last_file,
                exception=e.exception,
            )

    def _find_reports(self):
        checkpoint = self._checkpoint
        if not checkpoint.has_pending_reports():
            return self._query_new_report()
        return checkpoint.query_pending_reports()

    def _query_new_report(self):
        service = self._service
        checkpoint = self._checkpoint
        objects = service.objects()
        fields_to_return = "nextPageToken,items(name)"
        last_file = checkpoint.query_marker()
        prefix = self._report_prefix
        ingestion_start = self._ingestion_start
        bucket_name = self._bucket_name
        # if not prefix.endswith('-'):
        prefix += "-"

        if last_file is None:
            last_file = "{prefix}{date:%Y-%m-%d}".format(
                prefix=prefix, date=ingestion_start
            )

        page_token = self._make_page_token(last_file)
        page_token = page_token.decode("utf-8")

        request = objects.list(
            bucket=bucket_name,
            prefix=prefix,
            fields=fields_to_return,
            pageToken=page_token,
        )
        keys = []
        response = request.execute()
        items = response.get("items", [])
        keys.extend([item["name"] for item in items])
        if len(keys) > 0:
            last_key = keys[-1]
            checkpoint.pending_reports(keys)
            checkpoint.update_marker(last_key)
        return keys

    @classmethod
    def _make_page_token(cls, key):
        """assemble page token by key"""
        # key = key.encode('utf-8')
        length = len(key)
        token = ("\x0a" + chr(length) + key).encode("utf-8")
        token = base64.b64encode(token)
        return token

    def _process(self, key):
        checkpoint = self._checkpoint
        logger.info("processing report", file=key)
        with tempfile.TemporaryFile(dir=self._temp_file_folder) as cache:
            if self._download_report(key, cache):
                if self._ingest(key, cache):
                    checkpoint.remove_pending_report(key)

    def _ingest(self, key, cache):
        parser = None
        if key.endswith(".csv"):
            parser = self._parse_csv
        elif key.endswith(".json"):
            parser = self._parse_json

        if not parser:
            logger.warning("unknown report extension", file=key)
            return True

        source = "https://storage.cloud.google.com/{}/{}".format(self._bucket_name, key)
        try:
            data = parser(cache)
            self._event_writer.write_fileobj(data, source=source)
        except (ValueError, KeyError, TypeError):
            logger.exception("failed to parsing billing report", file=key)
        return True

    def _download_report(self, key, cache):
        try:
            objects = self._service.objects()
            request = objects.get_media(bucket=self._bucket_name, object=key)
            downloader = MediaIoBaseDownload(cache, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            cache.seek(0)
            return True
        except (GoogleAPIClientError, ProxyError):
            logger.exception("downloading report error", file=key)
        return False

    @staticmethod
    def _parse_json(cache):
        def _parse():
            records = json.load(cache)
            for item in records:
                yield json.dumps(item, sort_keys=True)

        return "\n".join(_parse())

    @staticmethod
    def _parse_csv(cache):
        def _parse():
            head = None
            for line in cache.readlines():
                line = line.rstrip("\n")
                if head is None:
                    head = line.split(",")
                    continue
                line = line.split(",")
                record = dict(list(zip(head, line)))
                yield json.dumps(record, sort_keys=True)

        return "\n".join(_parse())


class GoogleCloudBilling(object):
    def __init__(self):
        self._settings = None

    @LogExceptions(
        logger, "Modular input was interrupted by an unhandled exception.", lambda e: -1
    )
    def __call__(self, app, config):
        self._settings = Settings.load(config)
        self._settings.setup_log_level()
        inputs = BillingDataInputs(app, config)
        scheduler = app.create_task_scheduler(self.run_task)
        for name, params in inputs:
            scheduler.add_task(name, params, params.interval)

        if scheduler.idle():
            logger.info("No data input has been enabled.")

        scheduler.run([app.is_aborted, config.has_expired])
        return 0

    def run_task(self, app, name, params):
        return self._perform(app, name, params)

    @LogExceptions(
        logger, "Data input was interrupted by an unhandled exception.", lambda e: -1
    )
    def _perform(self, app, name, params):
        logger.info("data input started", data_input=name, **vars(params))
        config = app.create_config_service()
        credentials = self._create_credentials(config, params.profile)
        storage = self._build_storage_service(credentials)
        event_writer = app.create_event_writer(
            sourcetype=params.sourcetype, index=params.index
        )
        with app.open_checkpoint(name) as checkpoint:
            handler = BillingReportsHandler(
                checkpoint,
                event_writer,
                storage,
                params.bucket_name,
                params.report_prefix,
                params.ingestion_start,
                params.temp_file_folder,
            )
            handler.run()
        return 0

    def _build_storage_service(self, credentials):
        http = httplib2shim.Http(proxy_info=self._get_proxy_info, timeout=30)
        http = AuthorizedHttp(credentials, http=http)
        return build_service_client("storage", "v1", http=http, cache_discovery=False)

    def _get_proxy_info(self, scheme="http"):
        if scheme not in ["http", "https"]:
            return

        proxy = self._settings.make_proxy_uri()
        if not proxy:
            return
        parts = urlparse(proxy)
        proxy_scheme = parts.scheme

        traits = {
            "http": (PROXY_TYPE_HTTP, False),
            "socks5": (PROXY_TYPE_SOCKS5, False),
            "socks5h": (PROXY_TYPE_SOCKS5, True),
            "socks4": (PROXY_TYPE_SOCKS4, False),
            "socks4a": (PROXY_TYPE_SOCKS4, True),
        }
        if proxy_scheme not in traits:
            logger.warning("Unsupported proxy protocol.")
            return

        proxy_type, proxy_rdns = traits[proxy_scheme]
        proxy_user, proxy_pass = parts.username, parts.password
        if proxy_user:
            proxy_user = unquote(proxy_user)
        if proxy_pass:
            proxy_pass = unquote(proxy_pass)

        return httplib2.ProxyInfo(
            proxy_type=proxy_type,
            proxy_rdns=proxy_rdns,
            proxy_host=parts.hostname,
            proxy_port=parts.port,
            proxy_user=proxy_user,
            proxy_pass=proxy_pass,
        )

    @staticmethod
    def _create_credentials(config, profile):
        factory = CredentialFactory(config)
        scopes = ["https://www.googleapis.com/auth/cloud-platform.read-only"]
        credentials = factory.load(profile, scopes)
        return credentials


def main():
    arguments = {
        "placeholder": {"title": "A placeholder field for making scheme valid."}
    }
    SimpleCollectorV1.main(
        GoogleCloudBilling(),
        title="Google Billing Report",
        log_file_sharding=True,
        arguments=arguments,
    )
