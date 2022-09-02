#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#

import csv
import io
import json
import pathlib
import sys
import traceback
from builtins import object

import urllib3
from future import standard_library
from google.auth.transport.requests import AuthorizedSession
from google.cloud import storage
from googleapiclient import discovery
from googleapiclient.errors import HttpError
from splunk_ta_gcp.common.credentials import CredentialFactory
from splunk_ta_gcp.common.settings import Settings
from splunksdc import logging
from splunksdc.collector import SimpleCollectorV1
from splunksdc.config import BooleanField, IntegerField, StanzaParser, StringField
from splunksdc.utils import LogExceptions
from splunktalib.kv_client import KVClient, KVException, KVNotExists

standard_library.install_aliases()
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.get_module_logger()

DEFAULT_CHUNK_SIZE = 1048576
DEFAULT_SPLIT_TOKEN = ","
APP_NAME = "Splunk_TA_google-cloudplatform"
OBJECTS_COLLECTION = "google_cloud_bucket_objects"
BUCKET_METADATA_COLLECTION = "google_cloud_bucket_metadata"


class BucketsDataInputs(object):
    def __init__(self, app, config):
        self._app = app
        self._config = config

    def load(self):
        """
        Loads the parameters of the input from the conf file.
        """
        try:
            content = self._config.load("google_cloud_storage_buckets")
            for name, fields in list(content.items()):
                parser = StanzaParser(
                    [
                        BooleanField(
                            "disabled", default=False, reverse=True, rename="enabled"
                        ),
                        StringField("bucket_name", required=True),
                        StringField(
                            "google_credentials_name", required=True, rename="profile"
                        ),
                        StringField("google_project", required=True),
                        StringField(
                            "sourcetype", default="google:gcp:buckets:metadata"
                        ),
                        IntegerField("chunk_size", default=DEFAULT_CHUNK_SIZE),
                        IntegerField(
                            "polling_interval", default=3600, rename="interval"
                        ),
                        StringField("index"),
                    ]
                )
                params = parser.parse(fields)
                if params.enabled:
                    yield name, params
        except KeyError as key_error:
            logger.exception(key_error)
            logger.exception(
                "Some required values are missing in the configuration file. Please update with appropriate values."
            )
            return

    def __iter__(self):
        return self.load()


class GoogleCloudBucketsMetadata(object):
    def __init__(self):
        self._settings = None
        self.event_writer = None
        self.kv_client = None
        self.chunk_size = DEFAULT_CHUNK_SIZE

    @LogExceptions(
        logger, "Modular input was interrupted by an unhandled exception.", lambda e: -1
    )
    def __call__(self, app, config):
        self._settings = Settings.load(config)
        self._settings.setup_log_level()
        inputs = BucketsDataInputs(app, config)
        scheduler = app.create_task_scheduler(self.run_task)
        for name, params in inputs:
            scheduler.add_task(name, params, params.interval)
        if scheduler.idle():
            logger.info("No data input has been enabled.")
        scheduler.run([app.is_aborted, config.has_expired])
        return 0

    def run_task(self, app, name, params):
        self.validate_inputs(params, name)
        self.chunk_size = params.chunk_size
        self.google_project = params.google_project
        self.profile = params.profile
        logger.debug(
            "type of chunk_size {} value of chunk_size: {}".format(
                type(self.chunk_size), self.chunk_size
            )
        )

        return self.ingest_data(app, name, params)

    @LogExceptions(logger, traceback.format_exc(), lambda e: -1)
    def ingest_data(self, app, name, params):
        """
        Data Ingestion code for Cloud Bucket Metadata and files present in the bucket Input.

        @param: app
        @paramType: class object

        @param: name
        @paramType: string

        @param: params
        @paramType: dict
        """
        logger.info("-----Ingest Data Called-----")

        objects_collection_data, metadata_collection_data = self.get_collection_data(
            app
        )

        service, client = self.get_service_object(app, params.profile)
        self.event_writer = app.create_event_writer(index=params.index)
        buckets_list = params.bucket_name.split(",")

        for bucket_name in buckets_list:
            logger.info("Processing bucket: {}".format(bucket_name))

            """ create a bucket object """
            bucket = client.bucket(bucket_name)

            """ bucket metdata """
            request = service.buckets().get(bucket=bucket_name)
            response_bucket_metadata = request.execute()
            logger.info(
                "Successfully obtained bucket metadata for {}".format(bucket_name)
            )
            response_bucket_metadata["source"] = response_bucket_metadata["selfLink"]

            req = self.prepare_req(bucket_name, service)

            while req:

                response_object_metadata, req = self.get_metadata(
                    bucket_name, service, req
                )

                logger.debug(
                    f"Successfully obtained the next req iterator count = {len(response_object_metadata)}",
                    req,
                )

                items = response_object_metadata

                (checkpoint_fields) = self.get_checkpoint_fields(
                    name, bucket_name, items
                )

                files_to_ingest = self.get_list_of_files_to_be_ingested(
                    checkpoint_fields, objects_collection_data
                )

                self.ingest_files(client, bucket, params.index, files_to_ingest)

            logger.info(
                f"Successfully completed ingesting of objects in bucket= {bucket_name}"
            )

            logger.info("Ingest meta data for bucket {}".format(bucket_name))

            (
                ingest_bucket_metadata_flag,
                metadata_checkpoint,
            ) = self.get_ingest_bucket_metadata_flag(
                name,
                bucket_name,
                response_bucket_metadata,
                metadata_collection_data,
            )

            self.ingest_bucket_metadata(
                params,
                bucket_name,
                ingest_bucket_metadata_flag,
                response_bucket_metadata,
                metadata_checkpoint,
            )
            logger.info(
                f"Successfully completed Metadata ingestion for bucket= {bucket_name}"
            )
        return

    def ingest_files(self, client, bucket, index, files_to_ingest):
        sourcetypes = self.setup_sourcetypes()

        for file_dict in files_to_ingest:
            logger.debug("File Detail: {}".format(file_dict))

            # get name of file or blob to be downloaded
            filename = file_dict.get("filename")
            source = "{}:{}:{}:{}".format(
                self.profile,
                self.google_project,
                bucket.name,
                file_dict.get("filename"),
            )
            file_extension = self.file_extension(filename)

            logger.debug(
                "File extension: {} and sourcetype: {} source: {}".format(
                    file_extension,
                    sourcetypes.get(file_extension, "google:gcp:buckets:data"),
                    source,
                )
            )
            """ col1 | the value, is , something | col3 """

            # # create a blob object and get the size of the blob
            blob = bucket.get_blob(filename)
            blob_size = blob.size
            logger.debug("Size of blob: {}".format(blob_size))

            ingestion_status = dict()
            ingestion_status["completed"] = False

            end = -1
            success = False
            # until the full blob is ingested
            while ingestion_status.get("completed") is False:
                # create a temp file object
                blob_contents = io.BytesIO()

                # if blob is smaller than chunk size, ingesting in one download
                start = end + 1

                # if its a large file, ingest in chunks
                end = (
                    start + self.chunk_size
                    if start + self.chunk_size < blob_size
                    else blob_size
                )

                try:
                    logger.info(
                        "Ingesting file {} - chunk: start: {}, end: {}".format(
                            file_dict.get("filename"), start, end
                        )
                    )
                    client.download_blob_to_file(
                        blob_or_uri=blob, file_obj=blob_contents, start=start, end=end
                    )

                    if end >= blob_size:
                        logger.debug(
                            "This is the last chunk for {}".format(
                                file_dict.get("filename")
                            )
                        )
                        ingestion_status["completed"] = True
                except Exception as e:
                    logger.error("Exception {}".format(e))
                    ingestion_status["completed"] = True

                blob_contents.seek(0)
                success = self.ingest_file_content(
                    file_dict,
                    ingestion_status,
                    blob_contents,
                    source,
                    sourcetypes.get(file_extension, "google:gcp:buckets:data"),
                )
                blob_contents = None

            # Checkpoint
            if ingestion_status.get("completed", False) and success:
                file_dict["bytes_indexed"] = end
                logger.debug("Updating checkpoint for {}".format(file_dict))
                # update bytes ingested with
                try:
                    self.kv_client.insert_collection_data(
                        collection=OBJECTS_COLLECTION,
                        data=file_dict,
                        app=APP_NAME,
                        owner="nobody",
                    )
                    logger.debug(
                        "Updated checkpoint successfully for {}".format(filename)
                    )
                except KVException:
                    logger.exception(
                        "Failed to update object checkpoint data for {}".format(
                            filename
                        )
                    )
                    break
                except Exception:
                    logger.exception(
                        "Data was not Ingested for {}.".format(
                            file_dict.get("filename")
                        )
                    )
                    break

            file_dict.pop("filename")

    def _parse_csv_line(self, line):
        """Parses a csv line
            the built in csv parser is used to respect escapes etc.

        Args:
            line (string): line to parse

        Returns:
            list: fields as a list
        """
        if not isinstance(line, str):
            return []
        r = csv.reader([line], delimiter=DEFAULT_SPLIT_TOKEN)
        return list(r)[0]

    def ingest_file_content(
        self, file_dict, ingestion_status, response_chunk, source, sourcetype
    ):
        """
        Ingests data for the file.

        @param: file_dict
        @paramType: dict

        @param: response
        @paramType: string

        @param: source
        @paramType: string

        returns: None
        """
        try:
            # handle csv differently
            if sourcetype == "google:gcp:buckets:csvdata":
                # python will break the chunk into logical lines
                for response in response_chunk:
                    csv_stream = response.decode("utf-8")
                    # if it does not end with a new line then it
                    # is a partial line. Save the line to use it later
                    if not csv_stream.endswith("\n"):
                        logger.debug("Truncated Line:")
                        ingestion_status["truncated_line"] = csv_stream
                        continue

                    # if fieldnames is not populated then, it must be the first line of
                    # the file. extract the header
                    if ingestion_status.get("fieldnames", None) is None:

                        field_names = self._parse_csv_line(csv_stream)
                        """ pass the csv stream into stream and delimeter, if this quotation ignore until next quotation \
                        handle the escapes """

                        ingestion_status["fieldnames"] = field_names
                        logger.debug(
                            "Extracted Header: {}".format(
                                ingestion_status["fieldnames"]
                            )
                        )
                    else:
                        # if we had a truncated line from the previous chunk
                        # get that and prefix to the first line of current chunk
                        # reset it to None since we are done using the incomplete
                        # line
                        if ingestion_status.get("truncated_line", None):
                            logger.debug("Prefix previous partial line")
                            csv_stream = (
                                ingestion_status.get("truncated_line") + csv_stream
                            )
                            ingestion_status["truncated_line"] = None

                        # split by DEFAULT_SPLIT_TOKEN to get the values
                        values = self._parse_csv_line(csv_stream)
                        if len(values) < len(ingestion_status["fieldnames"]):
                            values += [""] * (
                                len(ingestion_status["fieldnames"]) - len(values)
                            )

                        # associate fields to values
                        csv_data = {
                            ingestion_status["fieldnames"][i]: values[i]
                            for i in range(len(ingestion_status["fieldnames"]))
                        }

                        self.event_writer.write_fileobj(
                            json.dumps(csv_data),
                            source=source,
                            sourcetype="google:gcp:buckets:csvdata",
                        )
            else:
                response = response_chunk.read().decode("utf-8")
                write_fileobj_chunk(
                    self.event_writer,
                    response,
                    completed=ingestion_status.get("completed", False),
                    source=source,
                    sourcetype=sourcetype,
                )
            logger.debug("Write events for {} ".format(file_dict.get("filename")))
            return True
        except UnicodeDecodeError:
            logger.info(
                "Cannot ingest contents of {}, file with this extention is not yet supported in the TA".format(
                    file_dict.get("filename")
                )
            )
            return False

    @staticmethod
    def _create_credentials(config, profile):
        """
        Method that returns credentials object which is further used to build service object

        @param: config
        @paramType class instance

        @param: profile
        @paramType: string

        returns: credentials object
        """
        factory = CredentialFactory(config)
        scopes = ["https://www.googleapis.com/auth/cloud-platform.read-only"]
        credentials = factory.load(profile, scopes)
        return credentials

    def setup_sourcetypes(self):
        sourcetype = {}
        sourcetype["csv"] = "google:gcp:buckets:csvdata"
        sourcetype["xml"] = "google:gcp:buckets:xmldata"
        sourcetype["json"] = "google:gcp:buckets:jsondata"
        sourcetype[""] = "google:gcp:buckets:data"
        logger.debug("Setup source types: {}".format(sourcetype))
        return sourcetype

    def file_extension(self, filename):
        file_extension = ""
        file_extension = pathlib.Path(filename).suffix[1:]
        if not file_extension:
            logger.debug("File does not have an extension. Returning empty string")
        return file_extension

    def validate_inputs(self, params, name):
        """
        Validates the parameters read from configuration files.

        @param: params
        @paramType dict like object

        @param: name
        @paramType: string

        returns: None
        """
        params.bucket_name = params.bucket_name.strip()
        params.index = params.index.strip()
        params.profile = params.profile.strip()
        params.google_project = params.google_project.strip()

        params.chunk_size = params.chunk_size
        logger.debug("Params obtained from conf file", data_input=name, **vars(params))
        if [x for x in vars(params).keys() if vars(params)[x] == ""]:
            logger.exception(
                "Empty values found in configuration file please enter/select appropriate value.",
                vars(params),
            )
            sys.exit(0)

    def get_collection_data(self, app):
        """
        Gets the collection data for bucket and objects present in the buckets.

        @param: app
        @paramType class instance

        returns: dicts of bucket and object collection data
        """
        try:
            mgmt_url = "https://{}:{}".format(
                app._context._server_host, app._context._server_port
            )
            self.kv_client = KVClient(
                splunkd_host=mgmt_url, session_key=app._context._token
            )
            objects_collection_data = self.kv_client.get_collection_data(
                collection=OBJECTS_COLLECTION, app=APP_NAME, key_id=None
            )
            logger.debug(
                "Objects checkpoint data:{} rows".format(len(objects_collection_data))
            )
            metadata_collection_data = self.kv_client.get_collection_data(
                collection=BUCKET_METADATA_COLLECTION, app=APP_NAME, key_id=None
            )
            logger.debug(
                "Metadata checkpoint data:{} rows".format(len(metadata_collection_data))
            )
            return objects_collection_data, metadata_collection_data
        except KVException:
            logger.exception("Failure in obtaining collection data.")
            sys.exit(0)

    def get_service_object(self, app, creds):
        """
        Returns the Storage service object created from the credentials

        @param: app
        @paramType class instance

        @param: creds
        @paramType: credentials object

        returns: service object
        """

        config = app.create_config_service()
        credentials = self._create_credentials(config, creds)
        session = AuthorizedSession(credentials)
        proxy = self._settings.make_proxy_uri()
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}
            session._auth_request.session.proxies = {
                "http": proxy,
                "https": proxy,
                "socks5": proxy,
            }

        service = discovery.build("storage", "v1", credentials=credentials)
        storage_client = storage.Client(credentials=credentials, _http=session)
        return service, storage_client

    def get_storage_client(self, app, creds):
        """
        Return a storage client that will be used to
        read a blob
        :param app:
        :type app:
        :param creds:
        :type creds:
        :return:
        :rtype:
        """
        storage_client = storage.Client(credentials=creds)
        return storage_client

    def prepare_req(self, bucket_name, service):
        """
        Gets the bucket metadata for the provided bucket

        @param: bucket_name
        @param: service

        returns: list of bucket metadata

        """

        try:
            # Getting objects metadata present in the bucket.
            req = service.objects().list(bucket=bucket_name)
            return req

        except HttpError as error:
            logger.exception(error)
            logger.exception(
                "Invalid bucket name to obtain metada {}".format(bucket_name)
            )
            sys.exit(0)

    def get_metadata(self, bucket_name, service, req):
        """
        Gets the object metadata for the provided bucket_name.

        @param: bucket_name
        @paramType: string

        @param: service
        @paramType: service object

        returns: response_object_metadata and next page oterator
        """
        try:

            response_object_metadata = []
            resp = req.execute()
            response_object_metadata.extend(resp.get("items", []))
            req = service.objects().list_next(req, resp)
            logger.info(
                "Successfully obtained object information present in the bucket {}.".format(
                    bucket_name
                )
            )

            return response_object_metadata, req

        except HttpError as error:
            logger.exception(error)
            logger.exception("Invalid bucket name {}".format(bucket_name))
            sys.exit(0)

    def get_checkpoint_fields(self, name, bucket_name, items):
        """
        Getting checkpoint related information from the metadatas of bucket and objects.

        @param: name
        @paramType: string

        @param: bucket_name
        @paramType: string

        @param: items
        @paramType: list

        @param: response_bucket_metadata
        @paramType: dict

        returns: list of dictionaries and dict
        """
        checkpoint_fields = []

        for item in items:
            item["source"] = item.pop("selfLink")
            checkpoint_fields.append(
                {
                    "filename": item.get("name"),
                    "md5Hash": item.get("md5Hash"),
                    "bytes_indexed": 0,
                    "_key": "{}_{}_{}_{}".format(
                        name, bucket_name, item.get("name"), item["timeCreated"]
                    ),
                }
            )

        logger.debug("DEBUG: Files Present in the bucket:{} files".format(bucket_name))

        return checkpoint_fields

    def get_list_of_files_to_be_ingested(
        self, checkpoint_fields, objects_collection_data
    ):
        """
        Returns the list of new files whose contents need to be ingested.

        @param: checkpoint_fields
        @paramType: list of dictionaries

        @param: objects_collection_data
        @paramType: list of dictionaries

        returns: list
        """
        files_to_ingest = []
        for checkpoint_field in checkpoint_fields:
            flag = False
            for data in objects_collection_data:
                if checkpoint_field.get("_key") == data.get(
                    "_key"
                ) and checkpoint_field.get("md5Hash") == data.get("md5Hash"):
                    flag = True
                    break
            if not flag:
                files_to_ingest.append(checkpoint_field)
        logger.info("Number of files to ingest: {}".format(len(files_to_ingest)))
        return files_to_ingest

    def get_ingest_bucket_metadata_flag(
        self, name, bucket_name, response_bucket_metadata, metadata_collection_data
    ):
        """
        Decides whether bucket_metadata needs to be ingested or not.

        @param: name
        @paramType: string

        @param: bucket_name
        @paramType: string

        @param: response_bucket_metadata
        @paramType: dict

        @param: metadata_collection_data
        @paramType: dict

        returns: boolean
        """
        metadata_checkpoint = {}
        ingest_bucket_metadata_flag = True

        metadata_checkpoint["updated"] = response_bucket_metadata["updated"]
        metadata_checkpoint["_key"] = "{}_{}_{}".format(
            name, bucket_name, response_bucket_metadata["timeCreated"]
        )

        if len(metadata_collection_data) > 0:
            for data in metadata_collection_data:
                if metadata_checkpoint.get("_key") == data.get(
                    "_key"
                ) and metadata_checkpoint.get("updated") == data.get("updated"):
                    ingest_bucket_metadata_flag = False
                    logger.info(
                        "No new Bucket Metadata is ingested for {}".format(bucket_name)
                    )
                    break

        return ingest_bucket_metadata_flag, metadata_checkpoint

    def ingest_bucket_metadata(
        self,
        params,
        bucket_name,
        ingest_bucket_metadata_flag,
        response_bucket_metadata,
        metadata_checkpoint,
    ):
        """
        Ingests the bucket metadata if new metadata is obtained.

        @param: params
        @paramType: dict

        @param: bucket_name
        @paramType: string

        @param: ingest_bucket_metadata_flag
        @paramType: boolean

        @param: response_bucket_metadata
        @paramType: dict

        @param: metadata_checkpoint
        @paramType: dict

        returns: None
        """
        # ingesting bucket metadata
        if ingest_bucket_metadata_flag:
            self.event_writer.write_events(
                [json.dumps(response_bucket_metadata)],
                source="{}:{}:{}".format(
                    params.profile, params.google_project, bucket_name
                ),
                sourcetype="google:gcp:buckets:metadata",
            )
            logger.info("Ingested bucket metadata for {}".format(bucket_name))
            try:
                logger.debug(
                    "Row to be updated in metadata checkpoint {}".format(
                        metadata_checkpoint
                    )
                )
                self.kv_client.update_collection_data(
                    collection=BUCKET_METADATA_COLLECTION,
                    data=metadata_checkpoint,
                    app=APP_NAME,
                    key_id=metadata_checkpoint.get("_key"),
                    owner="nobody",
                )
                logger.info("Updated metadata checkpoint successfully.")

            except KVNotExists:
                self.kv_client.insert_collection_data(
                    collection=BUCKET_METADATA_COLLECTION,
                    data=metadata_checkpoint,
                    app=APP_NAME,
                    owner="nobody",
                )
                logger.info("Updated metadata checkpoint successfully.")

            except KVException:
                logger.exception("Failed to update metadata checkpoint data.")
                sys.exit(0)


def write_fileobj_chunk(event_writer, fileobj, completed=False, **kwargs):
    volume = 0
    metadata = event_writer._compose_event_metadata(kwargs)
    logger.debug("Start writing data to STDOUT.", **metadata)
    for chunk in event_writer._read_multiple_lines(fileobj):
        volume += len(chunk)
        data = event_writer._render_element("data", chunk)
        data = event_writer._CHUNK_TEMPLATE.format(data=data, done="", **metadata)
        event_writer._write(data)

    if completed:
        logger.debug("Write EOS")
        eos = event_writer._CHUNK_TEMPLATE.format(data="", done="<done/>", **metadata)
        event_writer._write(eos)
    logger.debug("Wrote data to STDOUT success.", size=volume)
    return volume


def main():
    """
    Main Function
    """
    arguments = {
        "placeholder": {"title": "A placeholder field for making scheme valid."}
    }
    SimpleCollectorV1.main(
        GoogleCloudBucketsMetadata(),
        title="Google Buckets Metadata",
        log_file_sharding=True,
        arguments=arguments,
    )
