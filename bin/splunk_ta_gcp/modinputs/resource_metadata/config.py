#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import os
import os.path as op

import splunk_ta_gcp.legacy.config as gconf
import splunk_ta_gcp.legacy.consts as ggc
import splunktalib.conf_manager.conf_manager as cm
import splunktalib.file_monitor as fm
from splunksdc import log as logging
from splunktalib.common import util as scutil

from . import consts as grc

logger = logging.get_module_logger()


def create_conf_monitor(callback):
    """
    Returns a file moitor for configuration file
    """
    files = (
        GoogleResourceMetadataConfig.app_file,
        GoogleResourceMetadataConfig.conf_file_w_path,
        GoogleResourceMetadataConfig.task_file_w_path,
        GoogleResourceMetadataConfig.passwords_file_w_path,
    )

    return fm.FileMonitor(callback, files)


def get_app_path(absolute_path):
    """
    Returns a path to current app
    """
    marker = os.path.join(os.path.sep, "etc", "apps")
    start = absolute_path.rfind(marker)
    if start == -1:
        start = 0
    end = absolute_path.find("bin", start)
    if end == -1:
        return None

    # strip the tail
    end = end - 1
    path = absolute_path[:end]
    return path


class GoogleResourceMetadataConfig(gconf.GoogleConfig):
    """
    Creates tasks from resource metadata configuration file
    """

    app_dir = get_app_path(op.abspath(__file__))
    app_file = op.join(app_dir, "local", "app.conf")
    conf_file = "google_cloud_resource_metadata_inputs"
    conf_file_w_path = op.join(app_dir, "local", conf_file + ".conf")
    task_file = "google_cloud_resource_metadata_inputs_tasks"
    task_file_w_path = op.join(app_dir, "local", task_file + ".conf")
    passwords = "passwords"
    passwords_file_w_path = op.join(app_dir, "local", passwords + ".conf")

    def __init__(self):
        super(GoogleResourceMetadataConfig, self).__init__(grc.google_resource_metadata)

    @staticmethod
    def data_collection_conf():
        return grc.myta_resource_settings_conf

    def _get_tasks(self):
        self.task_file = self.data_collection_conf()
        conf_mgr = cm.ConfManager(
            self.metas[ggc.server_uri],
            self.metas[ggc.session_key],
            app_name=self._appname,
        )
        tasks = self._get_description_tasks(conf_mgr)
        self._assign_source(tasks)
        return tasks

    def _assign_source(self, tasks):
        for task in tasks:
            if not task.get(ggc.source):
                task[ggc.source] = "{google_zone}:{google_api}".format(**task)

    def _get_description_tasks(self, conf_mgr):
        stanzas = conf_mgr.all_stanzas(self.task_file)
        tasks, creds = [], {}
        for stanza in stanzas:
            if scutil.is_true(stanza.get(ggc.disabled)):
                continue

            tasks.extend(self._expand_tasks(stanza, creds))
        return tasks

    def _expand_tasks(self, stanza, creds):
        tasks = []
        creds = gconf.get_google_creds(
            self.metas[ggc.server_uri],
            self.metas[ggc.session_key],
            cred_name=stanza[ggc.google_credentials_name],
        )
        global_settings = gconf.get_global_settings(
            self.metas[ggc.server_uri], self.metas[ggc.session_key]
        )
        for api_interval in stanza[grc.apis].split(","):
            api_interval = api_interval.split("/")
            api_name = api_interval[0].strip()
            api_interval = int(api_interval[1].strip())

            for zone in stanza[grc.zones].split(","):
                zone = zone.strip()
                _task = {
                    ggc.server_uri: self.metas[ggc.server_uri],
                    ggc.session_key: self.metas[ggc.session_key],
                    ggc.google_project: stanza[ggc.google_project],
                    ggc.disabled: stanza[ggc.disabled],
                    grc.api: api_name,
                    ggc.google_credentials_name: stanza[ggc.google_credentials_name],
                    grc.zone: zone,
                    ggc.polling_interval: api_interval,
                    ggc.index: stanza[ggc.index],
                    ggc.sourcetype: stanza[ggc.sourcetype],
                }
                _task.update(global_settings[ggc.proxy_settings])
                _task.update(global_settings[ggc.global_settings])
                _task.update(creds[stanza[ggc.google_credentials_name]])
                _task.update(self.metas)
                _task[ggc.google_service] = self.service
                _task[ggc.appname] = self._appname
                tasks.append(_task)
        return tasks
