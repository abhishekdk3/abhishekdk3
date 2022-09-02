#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

import traceback

from google.auth.transport.requests import AuthorizedSession
from google.cloud import bigquery
from splunk_ta_gcp.common.credentials import CredentialFactory
from splunk_ta_gcp.common.settings import Settings
from splunksdc import log as logging
from splunksdc.config import (
    BooleanField,
    DateTimeField,
    IntegerField,
    StanzaParser,
    StringField,
)
from splunksdc.utils import LogExceptions

from . import bigquery_consts as bqc

logger = logging.get_module_logger()


class BigQueryDataInputs(object):
    def __init__(self, app, config):
        self._app = app
        self._config = config

    def load(self):
        content = self._config.load("google_cloud_billing_inputs")
        for name, fields in list(content.items()):
            parser = StanzaParser(
                [
                    BooleanField(
                        "disabled", default=False, reverse=True, rename="enabled"
                    ),
                    StringField("google_bq_dataset", required=True),
                    StringField("google_bq_table", required=True),
                    StringField(
                        "google_credentials_name", required=True, rename="profile"
                    ),
                    StringField("google_project", required=True),
                    StringField(
                        "sourcetype", default="google:gcp:bigquery:billing:report"
                    ),
                    IntegerField("google_bq_query_limit", default=bqc.bq_query_limit),
                    IntegerField(
                        "google_bq_request_page_size", default=bqc.bq_request_page_size
                    ),
                    DateTimeField("ingestion_start", default="1970-01-01"),
                    IntegerField("polling_interval", default=86400, rename="interval"),
                    StringField("index"),
                ]
            )
            params = parser.parse(fields)
            if params.enabled:
                yield name, params

    def __iter__(self):
        return self.load()


class GoogleCloudBigQuery(object):
    """
    BigQuery  object
    params: settings
    params:BigQuery Handler
    """

    def __init__(self, handler):
        self._settings = None
        self._report_handler = handler

    @LogExceptions(
        logger, "Modular input was interrupted by an unhandled exception.", lambda e: -1
    )
    def __call__(self, app, config):
        self._settings = Settings.load(config)
        self._settings.setup_log_level()
        inputs = BigQueryDataInputs(app, config)

        scheduler = app.create_task_scheduler(self.run_task)
        for name, params in inputs:
            scheduler.add_task(name, params, params.interval)

        if scheduler.idle():
            logger.info("No data input has been enabled.")

        scheduler.run([app.is_aborted, config.has_expired])
        return 0

    def run_task(self, app, name, params):
        return self._run_ingest(app, name, params)

    @LogExceptions(
        logger, "Data input was interrupted by an unhandled exception.", lambda e: -1
    )
    def _run_ingest(self, app, name, params):
        """
        All the steps involved in the pipeline to ingest data for application configured
        :param app: A request object that originates from the UI
        :param name: A data input name
        :param params: Parameters configured during input creation
        :return: 0
        """

        if len(params.google_bq_dataset) == 0:
            logger.warning(
                " Billing ingestion error. "
                + " You must use the Cloud BigQuery Billing input in order to ingest billing data. "
            )
            return

        logger.info("Data input started", data_input=name, **vars(params))
        config = app.create_config_service()

        # Step 1 - Create credentials object
        logger.debug("Calling create_credentials ")
        try:
            credentials = self._create_credentials(config, params.profile)
        except Exception as e:
            traceback.print_exc()
            raise e

        # Step 2 - Create a BigQuery Client
        logger.debug("Calling bigquery.Client")
        try:
            # Client to bundle configuration needed for API requests.
            bq_client = self._build_bigquery_client(credentials, params.google_project)

        except Exception as e:
            traceback.print_exc()
            raise e

        # Step 3 - Create a event writer
        logger.debug("Calling create_event_writer")
        try:
            event_writer = app.create_event_writer(
                sourcetype=params.sourcetype, index=params.index
            )

        except Exception as e:
            traceback.print_exc()
            raise e
        logger.debug("Calling Data Collection for {}".format(self._report_handler))

        # Step 4 - Start Data Collection
        with app.open_checkpoint(name) as checkpoint:
            handler = self._report_handler(
                checkpoint,
                event_writer,
                bq_client,
                name,
                params.google_project,
                params.google_bq_dataset,
                params.google_bq_table,
                params.google_bq_query_limit,
                params.google_bq_request_page_size,
                params.ingestion_start,
            )
            handler.run()

        return 0

    def _build_bigquery_client(self, credentials, google_project):
        session = AuthorizedSession(credentials)
        proxy = self._settings.make_proxy_uri()
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}
            session._auth_request.session.proxies = {
                "http": proxy,
                "https": proxy,
                "socks5": proxy,
            }

        return bigquery.Client(
            credentials=credentials, project=google_project, _http=session
        )

    """def _get_proxy_info(self, scheme="http"):
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
"""

    @staticmethod
    def _create_credentials(config, profile):
        factory = CredentialFactory(config)
        scopes = [
            "https://www.googleapis.com/auth/cloud-platform.read-only",
            "https://www.googleapis.com/auth/bigquery",
            "https://www.googleapis.com/auth/cloud-platform",
        ]
        credentials = factory.load(profile, scopes)
        return credentials
