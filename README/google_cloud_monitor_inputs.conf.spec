##
## SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
## SPDX-License-Identifier: LicenseRef-Splunk-8-2021
##
## Requirements Specific to the Addon for Testing

[<name>]
google_credentials_name = stanza name in google_credentials.conf
google_project = google project ID
google_metrics = google cloud monitor metrics, separated by ",". For instance, pubsub.googleapis.com/subscription/num_undelivered_messages,pubsub.googleapis.com/subscription/oldest_unacked_message_age. Refer to https://cloud.google.com/monitoring/api/metrics for the supported metrics list
polling_interval = data collection interval, 300 seconds by default
oldest = from which point of time to collect data, in %Y-%m-%dT%H:%M:%S format. For example, 2016-01-01T00:00:00
index = splunk index
