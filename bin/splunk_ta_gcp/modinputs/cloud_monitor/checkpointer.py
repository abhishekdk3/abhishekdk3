#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import base64
from builtins import object
from datetime import datetime, timedelta

import splunk_ta_gcp.legacy.consts as ggc
import splunktalib.state_store as sss

from . import consts as gmc

metric_date_fmt = "%Y-%m-%dT%H:%M:%S"


def add_timezone(metric_date_str):
    if not metric_date_str.endswith("-00:00"):
        metric_date_str = "{}-00:00".format(metric_date_str)
    return metric_date_str


def strip_off_timezone(metric_date_str):
    pos = metric_date_str.rfind("-00:00")
    if pos > 0:
        metric_date_str = metric_date_str[:pos]
    return metric_date_str


def strp_metric_date(metric_date_str):
    metric_date_str = strip_off_timezone(metric_date_str)
    return datetime.strptime(metric_date_str, metric_date_fmt)


def strf_metric_date(metric_date):
    mdate = datetime.strftime(metric_date, metric_date_fmt)
    return "{}-00:00".format(mdate)


def calculate_youngest(oldest, polling_interval, now, win=86400):
    """
    return (youngest, done)
    """

    win = max(polling_interval, win)
    youngest = oldest + timedelta(seconds=win)
    done = False
    if youngest >= now:
        youngest = now
        done = True

    return (youngest, done)


class GoogleCloudMonitorCheckpointer(object):
    def __init__(self, config):
        self._config = config
        key = "{stanza_name}|{metric_name}".format(
            stanza_name=config[ggc.name], metric_name=config[gmc.google_metrics]
        )
        self._key = base64.b64encode(key.encode("utf-8"))
        self._store = sss.get_state_store(
            config,
            config[ggc.appname],
            collection_name=ggc.google_cloud_monitor,
            use_kv_store=config.get(ggc.use_kv_store),
        )
        self._state = self._get_state()

    def _get_state(self):
        state = self._store.get_state(self._key)
        if not state:
            state = {
                gmc.oldest: strip_off_timezone(self._config[gmc.oldest]),
                "version": 1,
            }
        return state

    def oldest(self):
        return self._state[gmc.oldest]

    def set_oldest(self, oldest, commit=True):
        oldest = strip_off_timezone(oldest)
        self._state[gmc.oldest] = oldest
        if commit:
            self._store.update_state(self._key, self._state)

    def delete(self):
        self._store.delete_state(self._key)
