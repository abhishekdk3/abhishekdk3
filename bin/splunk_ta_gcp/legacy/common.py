# pylint: skip-file
#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
from __future__ import print_function

import datetime
import os.path as op
import sys
import time
from builtins import range

import google.auth
import pytz
import splunk_ta_gcp.legacy.consts as ggc
import splunktalib.common.util as scutil
import splunktalib.file_monitor as fm
import splunktalib.modinput as mi
import splunktalib.rest as sr
from google.oauth2 import service_account
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient import discovery
from pyrfc3339 import parse as rfc3339_parse

_EPOCH_TIME = datetime.datetime.utcfromtimestamp(0).replace(tzinfo=pytz.utc)


def validate_config():
    """
    Validate inputs.conf
    """

    return 0


def usage():
    """
    Print usage of this binary
    """

    hlp = "%s --scheme|--validate-arguments|-h"
    print(hlp % sys.argv[0], file=sys.stderr)
    sys.exit(1)


def print_scheme(title, description):
    """
    Feed splunkd the TA's scheme
    """

    print(
        """
    <scheme>
    <title>{title}</title>
    <description>{description}</description>
    <use_external_validation>true</use_external_validation>
    <streaming_mode>xml</streaming_mode>
    <use_single_instance>true</use_single_instance>
    <endpoint>
      <args>
        <arg name="name">
          <title>Unique name which identifies this data input</title>
        </arg>
        <arg name="placeholder">
          <title>placeholder</title>
        </arg>
      </args>
    </endpoint>
    </scheme>""".format(
            title=title, description=description
        )
    )


def main(scheme_printer, run):
    args = sys.argv
    if len(args) > 1:
        if args[1] == "--scheme":
            scheme_printer()
        elif args[1] == "--validate-arguments":
            sys.exit(validate_config())
        elif args[1] in ("-h", "--h", "--help"):
            usage()
        else:
            usage()
    else:
        # sleep 5 seconds here for KV store ready
        time.sleep(5)
        run()


def setup_signal_handler(loader, logger):
    """
    Setup signal handlers
    @data_loader: data_loader.DataLoader instance
    """

    def _handle_exit(signum, frame):
        logger.info("Exit signal received, exiting...")
        loader.tear_down()

    scutil.handle_tear_down_signals(_handle_exit)


def get_file_change_handler(loader, logger):
    def reload_and_exit(changed_files):
        logger.info("Conf file(s)=%s changed, exiting...", changed_files)
        loader.tear_down()

    return reload_and_exit


def get_configs(ConfCls, modinput_name, logger):
    conf = ConfCls()
    tasks = conf.get_tasks()

    if not tasks:
        logger.debug(
            "Data collection for %s is not fully configured. "
            "Do nothing and quit the TA.",
            modinput_name,
        )
        return None, None

    return conf.metas, tasks


def get_modinput_configs():
    modinput = sys.stdin.read()
    return mi.parse_modinput_configs(modinput)


def sleep_until(interval, condition):
    """
    :interval: integer
    :condition: callable to check if need break the sleep loop
    :return: True when during sleeping condition is met, otherwise False
    """

    for _ in range(interval):
        time.sleep(1)
        if condition():
            return True
    return False


def get_app_path(absolute_path):
    marker = op.join(op.sep, "etc", "apps")
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


def get_conf_files(files):
    cur_dir = get_app_path(op.abspath(__file__))
    all_files = []
    all_confs = [ggc.myta_global_settings_conf, ggc.myta_cred_conf] + files
    for f in all_confs:
        all_files.append(op.join(cur_dir, "local", f))
    return all_files


def create_conf_monitor(callback, files):
    return fm.FileMonitor(callback, get_conf_files(files))


def rfc3339_to_seconds(rfc3339_datetime_str):
    timestamp = rfc3339_parse(rfc3339_datetime_str)
    return (timestamp - _EPOCH_TIME).total_seconds()


def fqrn(resource_type, project, resource):
    """Return a fully qualified resource name for Cloud Pub/Sub."""
    return "projects/{}/{}/{}".format(project, resource_type, resource)


def create_google_client(config):
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
        "scopes": xxx,
        "service_name": xxx,
        "version": xxx,
    }
    """

    if config.get("google_credentials"):
        credentials = service_account.Credentials.from_service_account_info(
            config["google_credentials"]
        )
    else:
        credentials, project = google.auth.default()

    scopes = config.get("scopes")
    if scopes:
        credentials = credentials.with_scopes(scopes)

    http = sr.build_http_connection(config, timeout=config.get("pulling_interval", 30))
    http = AuthorizedHttp(credentials, http=http)
    client = discovery.build(
        config["service_name"], config["version"], http=http, cache_discovery=False
    )

    return client
