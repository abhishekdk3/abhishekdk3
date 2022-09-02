#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
# flake8: noqa: E402
from future import standard_library

standard_library.install_aliases()
import os
import queue
import threading
from builtins import object
from multiprocessing import Manager, Process

import splunk_ta_gcp.legacy.consts as ggc
import splunk_ta_gcp.modinputs.cloud_monitor.data_loader as gmdl
import splunktalib.common.util as scutil
import splunktalib.event_writer as ew
import splunktalib.orphan_process_monitor as opm
import splunktalib.timer_queue as tq
from splunksdc import log as logging

logger = logging.get_module_logger()


def create_data_loader(config):
    service_2_data_loader = {
        ggc.google_cloud_monitor: gmdl.GoogleCloudMonitorDataLoader,
    }

    assert config.get(ggc.google_service)
    assert config[ggc.google_service] in service_2_data_loader

    return service_2_data_loader[config[ggc.google_service]](config)


def _wait_for_tear_down(tear_down_q, loader):
    checker = opm.OrphanProcessChecker()
    while 1:
        try:
            go_exit = tear_down_q.get(block=True, timeout=2)
        except queue.Empty:
            go_exit = checker.is_orphan()
            if go_exit:
                logger.info("%s becomes orphan, going to exit", os.getpid())

        if go_exit:
            break

    if loader is not None:
        loader.stop()
    logger.info("End of waiting for tear down signal")


def _load_data(tear_down_q, task_config):
    loader = create_data_loader(task_config)
    thr = threading.Thread(target=_wait_for_tear_down, args=(tear_down_q, loader))
    thr.daemon = True
    thr.start()
    loader.index_data()
    thr.join()
    logger.info("End of load data")


class GoogleConcurrentDataLoader(object):
    def __init__(self, task_config, tear_down_q, process_safe):
        if process_safe:
            self._worker = Process(target=_load_data, args=(tear_down_q, task_config))
        else:
            self._worker = threading.Thread(
                target=_load_data, args=(tear_down_q, task_config)
            )

        self._worker.daemon = True
        self._started = False
        self._tear_down_q = tear_down_q
        self.name = task_config[ggc.name]

    def start(self):
        if self._started:
            return
        self._started = True

        self._worker.start()
        logger.info("GoogleConcurrentDataLoader started.")

    def tear_down(self):
        self.stop()

    def stop(self):
        if not self._started:
            return
        self._started = False

        self._tear_down_q.put(True)
        logger.info("GoogleConcurrentDataLoader is going to exit.")


class GoogleDataLoaderManager(object):
    def __init__(self, task_configs):
        self._task_configs = task_configs
        self._wakeup_queue = queue.Queue()
        self._timer_queue = tq.TimerQueue()
        self._mgr = None
        self._started = False
        self._stop_signaled = False

    def start(self):
        if self._started:
            return
        self._started = True

        self._timer_queue.start()

        process_safe = self._use_multiprocess()
        logger.info("Use multiprocessing=%s", process_safe)

        event_writer = ew.create_event_writer(self._task_configs[0], process_safe)
        event_writer.start()

        tear_down_q = self._create_tear_down_queue(process_safe)

        loaders = []
        for task in self._task_configs:
            task[ggc.event_writer] = event_writer
            loader = GoogleConcurrentDataLoader(task, tear_down_q, process_safe)
            loader.start()
            loaders.append(loader)

        logger.info("GoogleDataLoaderManager started")
        _wait_for_tear_down(self._wakeup_queue, None)
        logger.info("GoogleDataLoaderManager got stop signal")

        for loader in loaders:
            logger.info("Notify loader=%s", loader.name)
            loader.stop()

        event_writer.tear_down()
        self._timer_queue.tear_down()

        if self._mgr is not None:
            self._mgr.shutdown()

        logger.info("GoogleDataLoaderManager stopped")

    def tear_down(self):
        self.stop()

    def stop(self):
        self._stop_signaled = True
        self._wakeup_queue.put(True)
        logger.info("GoogleDataLoaderManager is going to stop.")

    def stopped(self):
        return not self._started

    def received_stop_signal(self):
        return self._stop_signaled

    def add_timer(self, callback, when, interval):
        return self._timer_queue.add_timer(callback, when, interval)

    def remove_timer(self, timer):
        self._timer_queue.remove_timer(timer)

    def _use_multiprocess(self):
        if not self._task_configs:
            return False

        return scutil.is_true(self._task_configs[0].get(ggc.use_multiprocess))

    def _create_tear_down_queue(self, process_safe):
        if process_safe:
            self._mgr = Manager()
            tear_down_q = self._mgr.Queue()
        else:
            tear_down_q = queue.Queue()
        return tear_down_q
