#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

from splunk_ta_gcp.modinputs.bigquery.common import GoogleCloudBigQuery
from splunksdc.collector import SimpleCollectorV1

from .billing_reports import BigQueryBillingReportsHandler


def main():
    arguments = {
        "placeholder": {"title": "A placeholder field for making scheme valid."}
    }
    SimpleCollectorV1.main(
        GoogleCloudBigQuery(BigQueryBillingReportsHandler),
        title="Google Bigquery Billing",
        log_file_sharding=True,
        arguments=arguments,
    )
