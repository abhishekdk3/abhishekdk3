#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
from google_cloud_bootstrap import run_module

if __name__ == "__main__":
    run_module("splunk_ta_gcp.modinputs.bucket_metadata")
