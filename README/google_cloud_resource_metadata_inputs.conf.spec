##
## SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
## SPDX-License-Identifier: LicenseRef-Splunk-8-2021
##
## Requirements Specific to the Addon for Testing

[<name>]
google_credentials_name = stanza name in google_credentials.conf
google_project = google project ID.
google_zones = google cloud zones, separated by ",".
google_apis = google cloud resource metadata api/interval separated by ",". For instance, instances/80, accelerator_types/60, autoscalers/60, disk_types/60.
sourcetype = splunk sourcetype name.
index = splunk index.
