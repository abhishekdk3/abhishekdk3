##
## SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
## SPDX-License-Identifier: LicenseRef-Splunk-8-2021
##
## Requirements Specific to the Addon for Testing

[global_settings]
log_level = log level of this AddOn
use_kv_store = 0 or 1. 1 means use KV Store to do checkpoint
use_multiprocess = 0 or 1. 1 means use multiprocess to do data collection, otherwise use multithreading
use_hec = 0 or 1. 1 means use Http Event Collector to inject data
hec_port = 8088, default HTTP input port
max_hec_event_size = 100000
base64encoded = 0 or 1. 1 means the events are base64 encoded in the google topic


[proxy_settings]
proxy_enabled = 0 or 1. 1 means enable proxy
proxy_url =
proxy_port =
proxy_username =
proxy_password =

# If use proxy to do DNS resolution, set proxy_rdns to 1
proxy_rdns = 0

# Valid proxy_type are http, socks4, socks5
proxy_type = http
