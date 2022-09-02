#
#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import threading
import time
import traceback
from builtins import object
from datetime import datetime, timedelta

import splunk_ta_gcp.legacy.common as tacommon
import splunk_ta_gcp.legacy.consts as ggc
from splunksdc import log as logging

from . import checkpointer as ckpt
from . import consts as gmc
from . import wrapper as gmw

logger = logging.get_module_logger()


class GoogleCloudMonitorDataLoader(object):
    def __init__(self, config):
        """
        :config: dict object
        {
            "appname": xxx,
            "use_kv_store": xxx,
            "proxy_url": xxx,
            "proxy_port": xxx,
            "proxy_username": xxx,
            "proxy_password": xxx,
            "proxy_rdns": xxx,
            "proxy_type": xxx,
            "google_credentials": xxx,
            "google_project": xxx,
            "google_metric": xxx,
            "index": xxx,
        }
        """

        interval = int(config.get(ggc.polling_interval, 120))
        config[ggc.polling_interval] = interval
        if not config.get(gmc.oldest):
            aweek_ago = datetime.utcnow() - timedelta(days=7)
            config[gmc.oldest] = ckpt.strf_metric_date(aweek_ago)

        self._config = config
        self._source = "{project}:{metric}".format(
            project=self._config[ggc.google_project],
            metric=self._config[gmc.google_metrics],
        )
        self._event_writer = None
        self._store = ckpt.GoogleCloudMonitorCheckpointer(config)
        self._lock = threading.Lock()
        self._stopped = False

    def get_interval(self):
        return self._config[ggc.polling_interval]

    def get_props(self):
        return self._config

    def stop(self):
        self._stopped = True
        logger.info("Stopping GoogleCloudMonitorDataLoader")

    def __call__(self):
        self.index_data()

    def index_data(self):
        if self._lock.locked():
            logger.info(
                "Last time of data collection for project=%s, " "metric=%s is not done",
                self._config[ggc.google_project],
                self._config[gmc.google_metrics],
            )
            return

        if self._event_writer is None:
            self._event_writer = self._config[ggc.event_writer]

        with self._lock:
            self._do_index()

    def _do_index(self):
        msg = "collecting data for datainput={}, project={}, metric={}".format(
            self._config[ggc.name],
            self._config[ggc.google_project],
            self._config[gmc.google_metrics],
        )
        logger.info("Start {}, from=%s".format(msg), self._store.oldest())
        try:
            self._do_safe_index()
        except Exception:
            logger.error("Failed of {}, error=%s".format(msg), traceback.format_exc())
        logger.info("End of {}".format(msg))

    def _do_safe_index(self):
        # 1) Cache max_events in memory before indexing for batch processing

        params = {
            ggc.google_project: self._config[ggc.google_project],
            gmc.google_metrics: self._config[gmc.google_metrics],
        }

        mon = gmw.GoogleCloudMonitor(logger, self._config)
        now = datetime.utcnow()
        oldest = ckpt.strp_metric_date(self._store.oldest())
        polling_interval = self._config[ggc.polling_interval]
        done, win = False, int(self._config.get("cm_win", 86400))
        while not done and not self._stopped:
            youngest, done = ckpt.calculate_youngest(oldest, polling_interval, now, win)
            params[gmc.oldest] = ckpt.strf_metric_date(oldest)
            params[gmc.youngest] = ckpt.strf_metric_date(youngest)
            logger.debug(
                "Collect data for project=%s, metric=%s, win=[%s, %s]",
                params[ggc.google_project],
                params[gmc.google_metrics],
                params[gmc.oldest],
                params[gmc.youngest],
            )

            metrics = mon.list_metrics(params)
            if metrics:
                latest = self._write_events(metrics)
                if not latest:
                    oldest = youngest
                else:
                    seconds = tacommon.rfc3339_to_seconds(latest)
                    oldest = datetime.utcfromtimestamp(seconds)
                self._store.set_oldest(params[gmc.youngest])
            else:
                # Sleep 2 seconds to avoid tight loop to consume API rate
                time.sleep(2)
                if (now - youngest).total_seconds() > win:
                    oldest += timedelta(seconds=win)
                    self._store.set_oldest(ckpt.strf_metric_date(oldest))
                    logger.info("Progress to %s", oldest)
                elif (youngest - oldest).total_seconds() >= win:
                    oldest += timedelta(seconds=win // 2)
                    self._store.set_oldest(ckpt.strf_metric_date(oldest))
                    logger.info("Progress to %s", oldest)

    def _create_event(self, metric):
        event_time = metric["points"][0].get("interval").get("startTime")
        try:
            event_time = tacommon.rfc3339_to_seconds(event_time)
        except Exception:
            logger.error(
                "Failed to parse rfc3339 datetime=%s, error=%s",
                event_time,
                traceback.format_exc(),
            )
            event_time = None

        event = self._event_writer.create_event(
            index=self._config[ggc.index],
            host=None,
            source=self._source,
            sourcetype="google:gcp:monitoring",
            time=event_time,
            unbroken=False,
            done=False,
            events=metric,
        )
        return event

    def _write_events(self, metrics):
        events, max_timestamp = [], ""
        for metric in metrics:
            if "points" not in metric or not metric["points"]:
                continue

            points = metric["points"]
            if len(points) > 1:
                # expand points
                del metric["points"]
                for point in points:
                    data_point = {}
                    data_point.update(metric)
                    data_point["points"] = [point]
                    event = self._create_event(data_point)
                    events.append(event)
                    if point["interval"]["endTime"] > max_timestamp:
                        max_timestamp = point["interval"]["endTime"]
            else:
                event = self._create_event(metric)
                events.append(event)
                max_timestamp = points[0]["interval"]["endTime"]

        self._event_writer.write_events(events, retry=10)
        return max_timestamp
