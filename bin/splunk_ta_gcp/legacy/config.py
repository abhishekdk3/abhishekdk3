#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
# flake8: noqa: E402
from future import standard_library

standard_library.install_aliases()
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from builtins import object

import splunk_ta_gcp.legacy.consts as ggc
import splunktalib.common.util as utils
import splunktalib.common.xml_dom_parser as xdp
import splunktalib.conf_manager.ta_conf_manager as tcm
import splunktalib.hec_config as hc
import splunktalib.modinput as modinput
import splunktalib.rest as sr
from splunksdc import log as logging

logger = logging.get_module_logger()


class GoogleConfig(object):
    _appname = ggc.splunk_ta_google

    def __init__(self, service):
        self.service = service
        metas, stanzas = modinput.get_modinput_configs_from_stdin()
        self.metas = metas
        self.stanzas = stanzas
        self._task_configs = self._get_tasks()
        self._handle_hec()

    @staticmethod
    def data_collection_conf():
        return None

    @staticmethod
    def _metric_key():
        return None

    @staticmethod
    def _get_metrics(logger, config):
        return []

    def _expand_metrics(self, task, global_settings, google_creds):
        # Maybe regex
        metrics = set(task[self._metric_key()].split(","))
        all_metrics = set()

        config = {}
        config.update(task)
        config.update(global_settings[ggc.proxy_settings])
        config.update(google_creds[task[ggc.google_credentials_name]])

        available_metircs = self._get_metrics(logger, config)
        for metric in metrics:
            for available_metirc in available_metircs:
                pmetric = metric
                if not metric.endswith("$"):
                    pmetric = "{metric}$".format(metric=metric)

                if re.match(pmetric, available_metirc) is not None:
                    all_metrics.add(available_metirc)
        logger.debug("All matched metrics=%s", all_metrics)
        return all_metrics

    def _get_tasks(self):
        conf_mgr = tcm.TAConfManager(
            self.data_collection_conf(),
            self.metas[ggc.server_uri],
            self.metas[ggc.session_key],
            appname=self._appname,
        )
        conf_mgr.reload()
        data_collections = conf_mgr.all(return_acl=False)
        if not data_collections:
            return []

        data_collections = {
            k: v
            for k, v in data_collections.items()
            if utils.is_false(v.get(ggc.disabled))
        }

        global_settings = get_global_settings(
            self.metas[ggc.server_uri], self.metas[ggc.session_key]
        )

        google_creds = get_google_creds(
            self.metas[ggc.server_uri], self.metas[ggc.session_key]
        )

        return self._expand_tasks(global_settings, google_creds, data_collections)

    def _expand_tasks(self, global_settings, google_creds, data_collections):
        keys = [ggc.index, ggc.name]
        metric_key = self._metric_key()
        all_tasks = []
        for task in data_collections.values():
            cred_name = task[ggc.google_credentials_name]
            if cred_name not in google_creds:
                logger.error("Invalid credential name ")
                continue

            metrics = self._expand_metrics(task, global_settings, google_creds)
            for metric in metrics:
                metric = metric.strip()
                if not metric:
                    continue

                new_task = {}
                new_task.update(task)
                with utils.save_and_restore(new_task, keys):
                    new_task.update(global_settings[ggc.global_settings])
                    new_task.update(global_settings[ggc.proxy_settings])
                    new_task.update(google_creds[cred_name])
                    new_task.update(self.metas)
                new_task[ggc.google_service] = self.service
                new_task[ggc.appname] = self._appname
                new_task[metric_key] = metric
                all_tasks.append(new_task)

        return all_tasks

    def get_tasks(self):
        return self._task_configs

    def _handle_hec(self):
        if not self._task_configs:
            return

        use_hec = utils.is_true(self._task_configs[0].get(ggc.use_hec))
        use_raw_hec = utils.is_true(self._task_configs[0].get(ggc.use_raw_hec))
        if not use_hec and not use_raw_hec:
            return

        hec = hc.HECConfig(self.metas[ggc.server_uri], self.metas[ggc.session_key])

        hec_input = hec.get_http_input("google_cloud_platform")
        port = self._task_configs[0].get(ggc.hec_port, 8088)
        if not hec_input:
            logger.info("Create HEC data input")
            hec_settings = {
                "enableSSL": 1,
                "port": port,
                "output_mode": "json",
                "disabled": 0,
            }
            hec.update_settings(hec_settings)
            input_settings = {
                "name": "google_cloud_platform",
            }
            hec.create_http_input(input_settings)
            hec_input = hec.get_http_input("google_cloud_platform")

        hostname, _ = utils.extract_hostname_port(self.metas[ggc.server_uri])
        hec_uri = "https://{hostname}:{port}".format(hostname=hostname, port=port)
        if hec_input:
            keys = [ggc.index, ggc.name]
            for task in self._task_configs:
                with utils.save_and_restore(task, keys):
                    task.update(hec_input[0])
                    task["hec_server_uri"] = hec_uri
        else:
            raise Exception("Failed to get HTTP input configuration")


def get_google_creds(
    server_uri, session_key, user="nobody", app=ggc.splunk_ta_google, cred_name=""
):
    """
    :param: get clear creds for cred_name.
    :return: a dict of dict which contains all creds. if cred_name is in
             (None, ""), return all creds
    """

    if not cred_name:
        cred_name = ""

    url = (
        "{server_uri}/servicesNS/{user}/{app}/splunk_ta_google"
        "/google_credentials/{name}?--get-clear-credential--=1"
    ).format(
        server_uri=server_uri,
        user=user,
        app=app,
        name=urllib.parse.quote(cred_name, safe=""),
    )
    response, content = sr.splunkd_request(url, session_key, method="GET")
    if not response or response.status not in (200, 201):
        raise Exception(
            "Failed to get google credentials for name={}. "
            "Check util log for more details".format(cred_name)
        )
    stanzas = xdp.parse_conf_xml_dom(content)
    creds = {}
    for stanza in stanzas:
        cred = json.loads(stanza[ggc.google_credentials])
        stanza[ggc.google_credentials] = cred
        creds[stanza[ggc.name]] = stanza
    return creds


def get_global_settings(
    server_uri, session_key, user="nobody", app=ggc.splunk_ta_google
):
    """
    :param: get global settings for global settings
    :return: a dict of dict which contains global settings .
    """

    url = (
        "{server_uri}/servicesNS/{user}/{app}/splunk_ta_google"
        "/google_settings?--get-clear-credential--=1"
    ).format(server_uri=server_uri, user=user, app=app)
    response, content = sr.splunkd_request(url, session_key, method="GET")
    if not response or response.status not in (200, 201):
        raise Exception(
            "Failed to get google global settings."
            "Check util log for more details %s" % url
        )
    stanzas = xdp.parse_conf_xml_dom(content)
    settings = {}
    for stanza in stanzas:
        settings[stanza[ggc.name]] = stanza

    if not utils.is_true(settings[ggc.proxy_settings].get(ggc.proxy_enabled)):
        settings[ggc.proxy_settings][ggc.proxy_url] = None

    return settings


def get_google_settings(server_uri, session_key, cred_name):
    creds = get_google_creds(server_uri, session_key, cred_name=cred_name)
    global_settings = get_global_settings(server_uri, session_key)
    settings = {}
    settings.update(creds[cred_name])
    settings.update(global_settings[ggc.proxy_settings])
    return settings
