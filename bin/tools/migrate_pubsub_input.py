#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
from __future__ import print_function

import codecs
import configparser
import os
import shutil

from future import standard_library

standard_library.install_aliases()


SCRIPT_PATH = os.path.abspath(os.path.dirname(__file__))
LOCAL_FOLDER_PATH = "../../local"


def migrate_pubsub_inputs():
    print("Migrate inputs from google_pubsub_inputs.conf")

    old_input_path = os.path.join(
        SCRIPT_PATH, LOCAL_FOLDER_PATH, "google_pubsub_inputs.conf"
    )
    new_input_path = os.path.join(SCRIPT_PATH, LOCAL_FOLDER_PATH, "inputs.conf")

    # get old config
    if not os.path.isfile(old_input_path):
        print("Exit - no pubsub inputs were created.")
        return

    old_config = configparser.ConfigParser()
    with codecs.open(old_input_path, "r", "utf_8_sig") as fp:
        old_config.readfp(fp)

    # prepare new config file if not exist
    if not os.path.isfile(new_input_path):
        print("Create inputs.conf if not exist")
        open(new_input_path, "a").close()

    # open new config file
    new_config = configparser.ConfigParser()
    with codecs.open(new_input_path, "r", "utf_8_sig") as fp:
        new_config.readfp(fp)

    # migrate old input one by one
    for old_input in old_config.sections():
        attributes = old_config.items(old_input)
        _new_pubsub_input(new_config, old_input, attributes)

    # write to config file
    with codecs.open(new_input_path, "w", "utf_8") as fp:
        print("Write into file")
        new_config.write(fp)

    # end of migration
    print("Migration completes")


def _new_pubsub_input(new_config, old_name, attributes):
    STANZA_PREFIX = "google_cloud_pubsub://"
    # keep the name identical with the old one
    new_name = STANZA_PREFIX + old_name

    if new_config.has_section(new_name):
        print(
            'Input "{0}" is exist. Migration of "{1}" may already be processed.'.format(
                new_name, old_name
            )
        )
        return

    # create new input
    new_config.add_section(new_name)
    for k, v in attributes:
        new_config.set(new_name, k, v)

    # print('New input "{0}" is created.'.format(new_name))


def update_passwords_conf(old_config_name, new_config_name):
    print("Replace names in passwords.conf")

    password_path = os.path.join(SCRIPT_PATH, LOCAL_FOLDER_PATH, "passwords.conf")

    if not os.path.isfile(password_path):
        print("Nothing to be updated in passwords.conf")
        return

    old_passwords_conf = configparser.ConfigParser()
    with codecs.open(password_path, "r", "utf_8_sig") as fp:
        old_passwords_conf.readfp(fp)

    new_passwords_conf = configparser.ConfigParser()

    for section in old_passwords_conf.sections():
        old_prefix = "credential:__REST_CREDENTIAL__#Splunk_TA_google-cloudplatform#configs/conf-{0}#".format(
            old_config_name
        )
        new_prefix = "credential:__REST_CREDENTIAL__#Splunk_TA_google-cloudplatform#configs/conf-{0}#".format(
            new_config_name
        )

        new_section_name = section
        if section.startswith(old_prefix):
            new_section_name = new_prefix + section[len(old_prefix) :]  # noqa
            # do override
            if new_passwords_conf.has_section(new_section_name):
                new_passwords_conf.remove_section(new_section_name)
        elif new_passwords_conf.has_section(new_section_name):
            # skip
            continue

        attributes = old_passwords_conf.items(section)
        new_passwords_conf.add_section(new_section_name)
        for k, v in attributes:
            new_passwords_conf.set(new_section_name, k, v)

    # override passwords.conf
    with codecs.open(password_path, "w", "utf_8") as fp:
        print("override passwords.conf")
        new_passwords_conf.write(fp)


def rename_conf_files(old_file_name, new_file_name):
    print("Rename {0}.conf to {1}.conf".format(old_file_name, new_file_name))

    old_config_path = os.path.join(
        SCRIPT_PATH, LOCAL_FOLDER_PATH, "{0}.conf".format(old_file_name)
    )
    new_config_path = os.path.join(
        SCRIPT_PATH, LOCAL_FOLDER_PATH, "{0}.conf".format(new_file_name)
    )

    # get old config
    if not os.path.isfile(old_config_path):
        print("Exit - no {0}.conf were created.".format(old_file_name))
        return

    old_config = configparser.ConfigParser()
    with codecs.open(old_config_path, "r", "utf_8_sig") as fp:
        old_config.readfp(fp)

    # prepare new config file if not exist
    if not os.path.isfile(new_config_path):
        print("Create {0}.conf if not exist".format(new_file_name))
        open(new_config_path, "a").close()

    # open new config file
    new_config = configparser.ConfigParser()
    with codecs.open(new_config_path, "r", "utf_8_sig") as fp:
        new_config.readfp(fp)

    # migrate items one by one
    for section in old_config.sections():
        if new_config.has_section(section):
            print(
                'Section "{0}" is exist. Migration of "{0}" may already be processed.'.format(
                    section
                )
            )
            continue

        # create new section
        new_config.add_section(section)
        for k, v in old_config.items(section):
            new_config.set(section, k, v)

        print('Migration of section "{0}" is completed.'.format(section))

    # write to config file
    with codecs.open(new_config_path, "w", "utf_8") as fp:
        print("Write into {0}.conf".format(new_file_name))
        new_config.write(fp)

    update_passwords_conf(old_file_name, new_file_name)

    # end of migration
    print("Migration completes")


def remove_unused_packages():
    print("Remove unused python files")

    bin_folder = os.path.join(SCRIPT_PATH, "../")

    if os.path.isfile(os.path.join(bin_folder, "six.py")):
        os.remove(os.path.join(bin_folder, "six.py"))
    if os.path.isfile(os.path.join(bin_folder, "umsgpack.py")):
        os.remove(os.path.join(bin_folder, "umsgpack.py"))
    if os.path.isfile(os.path.join(bin_folder, "remote_pdb.py")):
        os.remove(os.path.join(bin_folder, "remote_pdb.py"))

    shutil.rmtree(os.path.join(bin_folder, "googleapiclient"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "httplib2"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "oauth2client"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "pyasn1"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "pyasn1_modules"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "rsa"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "simplejson"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "sortedcontainers"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "uritemplate"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "pyrfc3339"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "pytz"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "urllib3"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "dateutil"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "mako"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "markupsafe"), ignore_errors=True)
    shutil.rmtree(os.path.join(bin_folder, "splunklib"), ignore_errors=True)


if __name__ == "__main__":
    migrate_pubsub_inputs()
    rename_conf_files("google_global_settings", "google_cloud_global_settings")
    rename_conf_files("google_credentials", "google_cloud_credentials")
    remove_unused_packages()
