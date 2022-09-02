#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import json
from builtins import object

import urllib3
from future import standard_library
from splunksdc import log as logging

logger = logging.get_module_logger()

standard_library.install_aliases()

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class BigQueryBillingSourceTypes(object):
    """
    source type object
    param - table_id
    """

    def __init__(self, table_id):
        self._table_id = table_id

    def get_sourcetype(self):
        """
        This method set the source type based on billing report
        Standard Usage Cost Table = google:gcp:billing:standard_usage_cost
        Detailed Usage Cost Table = google:gcp:billing:detailed_usage_cost
        Pricing Table = google:gcp:billing:pricing

        params: table id
        return source_type
        """
        if self._table_id == "cloud_pricing_export":
            return "google:gcp:billing:pricing"
        elif self._table_id.find("resource") > 0:
            return "google:gcp:billing:standard_usage_cost"
        else:
            return "google:gcp:billing:detailed_usage_cost"


class BigQueryBillingIngestionCheckpoint(object):
    """
    Checkpoint object
    param - store
    """

    def __init__(self, store):
        # store the checkpoint file that is opened already
        self._store = store

    def set_checkpoint(self, key, export_time, offset):
        """
        Store the export_time, offset
        param - key
        param  - export_time
        """
        self._store.set("/export_time/" + key, f"{export_time},{offset}")

    def get_checkpoint(self, key):
        """
        Get the export_time,offset
        param - key
        return: export_time,offset if key is valid else None,0
        """
        if key is None:
            return None, 0
        try:
            if self._store.find("/export_time/" + key):
                result = self._store.get("/export_time/" + key).split(",")
                if len(result) == 2:
                    return result[0], int(result[1])
        except AttributeError as ex:
            logger.error("checkpoint value corrupt, clearing checkpoint", ex)

        return None, 0


class BigQueryBillingReportsHandler(object):
    """
    Report handler object
    param - ingestion_start
    param  - dataset_name
    param - input name
    param  - table_name
    param  - project_id
    param  - bq_client
    param  - event_writer
    param  - checkpoint
    param  - dataset_name
    param - Query limit
    param - Query request page size

    """

    def __init__(
        self,
        checkpoint=None,
        event_writer=None,
        bq_client=None,
        data_input=None,
        project_id=None,
        dataset_name=None,
        table_name=None,
        query_limit=None,
        request_page_size=None,
        ingestion_start=None,
    ):
        self._ingestion_start = ingestion_start
        self._bq_dataset = dataset_name
        self._bq_table = table_name
        self._project_id = project_id
        self._bq_query_limit = query_limit
        self._request_page_size = request_page_size
        self.table_id = "{}.{}.{}".format(
            self._project_id, self._bq_dataset, self._bq_table
        )

        self._checkpoint = BigQueryBillingIngestionCheckpoint(checkpoint)
        self._bq_client = bq_client
        self._event_writer = event_writer
        self._sourcetype = BigQueryBillingSourceTypes(self._bq_table)
        self._chkpointkey = "{}.{}".format(data_input, self.table_id)

    def run(self):

        logger.debug(
            "Calling bigquery_query_table_rows {} {} ".format(
                self._bq_query_limit, self._request_page_size
            )
        )
        # Fetch bigquery tablelist
        query_count = 0
        rows = []
        row_len = 0

        logger.info(f"Start querying/indexing BigQuery Table {self.table_id} ")

        try:
            while row_len == self._bq_query_limit or query_count == 0:
                query_count += 1

                start_time, offset = self._checkpoint.get_checkpoint(self._chkpointkey)
                if not start_time:
                    start_time = self._ingestion_start

                rows = self.bigquery_query_table_rows(
                    self._bq_query_limit, start_time, offset
                )
                if not rows:
                    # if first while iteration
                    if query_count == 1:
                        logger.info("reports not found.")
                    return
                row_len = rows.total_rows

                # Step 5 - index events
                self.index_events(rows, start_time, offset)

            logger.info(f"Finish querying/indexing BigQuery {query_count}")

        except Exception as ex:  # pylint: disable=bare-except
            logger.error(f"BigQuery Ingest failed on {query_count} {str(ex)} iteration")

    def bigquery_query_table_rows(self, query_limit=0, start_time=None, offset=0):
        """
        bigquery_query_table_rows: It queries and returns all rows from table
        It uses project ID, dataset and table name to query rows from table
        passes each row into the event writer

        return: rows[] | None
        """

        logger.info(
            "Tables contained in dataset name '{} and table_id {}':".format(
                self._bq_dataset, self.table_id
            )
        )

        logger.debug("Offset {} and key is {}".format(offset, self._chkpointkey))

        query = (
            """ SELECT * FROM `%s` WHERE export_time < TIMESTAMP_SUB(CURRENT_TIMESTAMP, INTERVAL %d MINUTE) AND export_time >= '%s' order by export_time LIMIT %d OFFSET %d """
        ) % (self.table_id, 20, start_time, query_limit, offset)

        logger.debug(
            " Making Query {query} page_size {page_size} LIMIT {LIMIT} ".format(
                query=query, page_size=self._request_page_size, LIMIT=query_limit
            )
        )

        query_job = self._bq_client.query(query)  # Make an API request.

        # define request from client to the temp table how big the request to be
        # limit --> temp  table size
        #                -> iterate the temp table based on the page size
        #

        rowiterator = query_job.result(page_size=self._request_page_size)
        if query_job.error_result:
            raise (Exception(query_job.error_result))

        return rowiterator

    def index_events(self, bigquery_rows, start_time, offset):
        """
        index_events: It indexes table data
        params:bigquery_rows : Table list
        params:start_time
        params:offset
        """
        prev_export_time = start_time

        logger.info(
            "Indexing {rows} rows and start_time {start_time} , offset {offset} ".format(
                rows=bigquery_rows.total_rows, start_time=start_time, offset=offset
            )
        )
        for row in bigquery_rows:
            json_obj = json.dumps(dict(row), sort_keys=True, default=str)

            try:
                self._event_writer.write_fileobj(
                    json_obj,
                    source=self._bq_table,
                    sourcetype=self._sourcetype.get_sourcetype(),
                )
            except (ValueError, KeyError, TypeError):
                logger.exception(
                    "Failed to parsing billing report", table=self._bq_table
                )

            checkpoint_time = row["export_time"]
            if str(checkpoint_time) == str(prev_export_time):
                offset += 1
            else:
                prev_export_time = checkpoint_time
                offset = 1

            # make sure checkpoint_time as a string (sort by date )
            self._checkpoint.set_checkpoint(self._chkpointkey, checkpoint_time, offset)
