##
## SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
## SPDX-License-Identifier: LicenseRef-Splunk-8-2021
##
## Requirements Specific to the Addon for Testing

[<name>]
google_credentials_name = stanza name in google_credentials.conf
google_project = the project name
google_bg_dataset = dataset name
google_bq_table = table name
google_bq_query_limit = This limits the rows returned from a big query query
google_bq_request_page_size = The maximum rows each request to big query will return.
ingestion_start = UTC Date YYYY-MM-DD
index =
polling_interval =
