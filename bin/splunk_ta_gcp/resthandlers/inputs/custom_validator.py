#
# SPDX-FileCopyrightText: 2021 Splunk, Inc. <sales@splunk.com>
# SPDX-License-Identifier: LicenseRef-Splunk-8-2021
#
#
import logging
import sys
from builtins import str

from splunktaucclib.rest_handler.endpoint import validator
from splunktaucclib.rest_handler.error_ctl import RestHandlerError as RH_Err

basestring = str if sys.version_info[0] == 3 else basestring  # type: ignore # Python 3 compatibility


class StringValidator(validator.Validator):
    """
    A custom validator that accepts non-whitespace characters.
    Accepted condition: min_len <= len(value) < max_len
    """

    def __init__(self, min_len=None, max_len=None):
        """
        :param min_len: If not None, it should be shorter than ``min_len``
        :param max_len: If not None, it should be longer than ``max_len``
        """

        def check(val):
            err_msg = "min_len & max_len should be non-negative integers"
            try:
                if not ((val is None) or (isinstance(val, (int, long)) and val >= 0)):
                    raise AssertionError(err_msg)
            except NameError:
                if not ((val is None) or (isinstance(val, int) and val >= 0)):
                    raise AssertionError(err_msg)

        check(min_len)
        check(max_len)
        super(StringValidator, self).__init__()
        self._min_len, self._max_len = min_len, max_len

    def validate(self, value, data):

        if not isinstance(value, basestring):
            self.put_msg("Input value should be string")
            return False
        msg = None
        value = value.strip()
        str_len = len(value)
        if None not in (self._min_len, self._max_len):
            if not self._min_len <= str_len < self._max_len:
                msg = "String length should be between {} and {} Value={}" "".format(
                    self._min_len, self._max_len, value
                )

        elif self._min_len is not None and str_len < self._min_len:
            msg = "String should be no shorter than {}".format(self._min_len)

        elif self._max_len is not None and str_len > self._max_len:
            msg = "String should be shorter than {}".format(self._max_len)

        # Input should contain only non-whitespace charaters
        regexp = r"([^\s]+)"
        pattern_validator = validator.Pattern(regexp)
        if not pattern_validator.validate(value, data):
            msg = "Input cannot not be empty"
        if msg is not None:
            self.put_msg(msg, True)
            return False
        else:
            return True


class APIValidator(validator.Validator):
    """Validates format of API"""

    def __init__(self, *args, **kwargs):
        super(APIValidator, self).__init__(*args, **kwargs)

    def validate(self, value, data):
        api_intervals = value.split(",")
        if api_intervals:
            for api_interval in api_intervals:
                # Checking if the each element in expected of api/interval
                regexp = r"\w[\w\/\-]+\/-?\d+"
                pattern_validator = validator.Pattern(regexp)
                if pattern_validator.validate(api_interval.strip(), data):
                    api_interval_list = api_interval.split("/")
                    if len(api_interval_list) <= 1:
                        msg = (
                            'Interval for api "'
                            + (api_interval_list[0]).replace("_", " ")
                            + '" should not be empty'
                        )
                        self.put_msg(msg, True)
                        return False

                    else:
                        # Checking if interval is negative
                        if int(api_interval_list[1]) <= 0:
                            msg = (
                                'Interval for api "'
                                + (api_interval_list[0]).replace("_", " ")
                                + '" should be greater than or equal to 1'
                            )
                            self.put_msg(msg, True)
                            return False
                else:
                    msg = (
                        'List of APIs "'
                        + (api_interval).replace("_", " ")
                        + '" not in expected format: <api_endpoint>/<interval>'
                    )
                    self.put_msg(msg, True)
                    return False
            return True
        else:
            return False


class DateValidator(validator.Datetime):
    """Validates date format"""

    # Future date should not accepted
    def __init__(self, datetime_format):
        super(DateValidator, self).__init__(datetime_format)

    def validate(self, value, data):
        from datetime import datetime

        try:
            input_date = datetime.strptime(value, self._format)
            now = datetime.utcnow()
            if input_date > now:
                self.put_msg("Date in future", True)
                return False

        except ValueError as exc:
            self.put_msg(str(exc))
            return False
        return True


class MetricValidator(validator.Validator):
    """Validates the metrics for monitoring inputs."""

    def __init__(self):
        super(MetricValidator, self).__init__()

    def validate(self, value, data):
        # .* is allowed for all metrics
        if value == ".*":
            return True

        # Checking if each metric is in valid format
        metric_list = value.split(",")
        for metric in metric_list:
            regexp = r"\w[\w\/\-\.]+"
            pattern_validator = validator.Pattern(regexp)
            if not pattern_validator.validate(metric, data):
                msg = "Monitoring Metrics contains invalid characters"
                self.put_msg(msg, True)
                return False

        return True


class RequiredValidator(object):
    """Validates if a field is required."""

    def __init__(self, requiredArgs=None):
        self.requiredArgs = requiredArgs

    def validate_required(self, params):
        # Required Arguments can not be None in payload
        if self.requiredArgs:
            for key in self.requiredArgs:
                if params.get(key) is None:
                    RH_Err.ctl(
                        400,
                        msgx="{} is a required argument".format(key),
                        logLevel=logging.ERROR,
                    )
                    return False
        return True
