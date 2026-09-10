# coding=utf-8

# Tests for the numeric range validation in SpoolManagerAPI's JSON coercion helpers.
#
# The maxValue side exists because of a known bad data source rather than fat-fingered
# input: TigerTags written before the firmware's factor-60 fix carry MINUTES in the byte
# that is defined as hours, so a spool dried for 3 h reads back as 180. There is no way to
# tell such a tag from a genuine one - 255 is 255 either way - so the only defence is
# refusing values that cannot be a real drying time at all.
#
# Only the helpers are exercised here: they are pure apart from a logger, so this needs
# none of the flask/OctoPrint/database scaffolding a full SpoolManagerAPI test would.
#
# Run with:  .venv/bin/python -m pytest octoprint_SpoolManagerExtended/test/test_NumericFieldValidation.py -v

import logging
import unittest

from octoprint_SpoolManagerExtended.api.SpoolManagerAPI import SpoolManagerAPI


class _Coercions(SpoolManagerAPI):
    """Just the coercion helpers - SpoolManagerAPI.__init__ is deliberately not called,
    since the helpers only ever touch self._logger and self._fieldLabel()."""

    def __init__(self):
        self._logger = logging.getLogger("test")


class TestIntRangeValidation(unittest.TestCase):
    def setUp(self):
        self.api = _Coercions()

    def test_value_inside_the_range_is_accepted(self):
        errors = []
        value = self.api._toIntFromJSONOrNone(
            "dryingTime", {"dryingTime": 8}, errors, minValue=0, maxValue=720
        )

        self.assertEqual(8, value)
        self.assertEqual([], errors)

    def test_value_exactly_at_the_maximum_is_accepted(self):
        # 720 h = 30 days: the boundary itself has to pass, or the cap would reject a value
        # it was chosen to permit
        errors = []
        value = self.api._toIntFromJSONOrNone(
            "dryingTime", {"dryingTime": 720}, errors, minValue=0, maxValue=720
        )

        self.assertEqual(720, value)
        self.assertEqual([], errors)

    def test_value_above_the_maximum_is_reported(self):
        errors = []
        self.api._toIntFromJSONOrNone(
            "dryingTime", {"dryingTime": 721}, errors, minValue=0, maxValue=720
        )

        self.assertEqual(1, len(errors))
        self.assertIn("must not be greater than 720", errors[0])

    def test_the_minutes_bug_value_is_rejected(self):
        # The case this cap exists for: an old TigerTag reporting 3 h as 180 stays inside
        # the range, but the larger ones this produces do not. 1500 is what a 25 h cycle
        # turns into.
        errors = []
        self.api._toIntFromJSONOrNone(
            "dryingTime", {"dryingTime": 1500}, errors, minValue=0, maxValue=720
        )

        self.assertEqual(1, len(errors))

    def test_without_a_maximum_nothing_is_capped(self):
        # every other caller passes minValue only - their behaviour must be untouched
        errors = []
        value = self.api._toIntFromJSONOrNone(
            "totalWeight", {"totalWeight": 999999}, errors, minValue=0
        )

        self.assertEqual(999999, value)
        self.assertEqual([], errors)

    def test_both_bounds_can_fail_independently(self):
        tooSmall = []
        self.api._toIntFromJSONOrNone(
            "dryingTime", {"dryingTime": -1}, tooSmall, minValue=0, maxValue=720
        )
        self.assertIn("must not be less than 0", tooSmall[0])

    def test_a_non_numeric_value_still_fails_as_before(self):
        # the max check must not swallow the "not a number" path
        errors = []
        value = self.api._toIntFromJSONOrNone(
            "dryingTime", {"dryingTime": "eight"}, errors, minValue=0, maxValue=720
        )

        self.assertIsNone(value)
        self.assertEqual(1, len(errors))
        self.assertIn("whole number", errors[0])


class TestFloatRangeValidation(unittest.TestCase):
    def setUp(self):
        self.api = _Coercions()

    def test_td_inside_its_defined_range_is_accepted(self):
        errors = []
        value = self.api._toFloatFromJSONOrNone(
            "td", {"td": 12.5}, errors, minValue=0, maxValue=100
        )

        self.assertAlmostEqual(12.5, value)
        self.assertEqual([], errors)

    def test_td_above_its_defined_range_is_reported(self):
        # TD is a dimensionless opacity number defined as 0.1-100
        errors = []
        self.api._toFloatFromJSONOrNone(
            "td", {"td": 100.5}, errors, minValue=0, maxValue=100
        )

        self.assertEqual(1, len(errors))
        self.assertIn("must not be greater than 100", errors[0])

    def test_without_a_maximum_nothing_is_capped(self):
        errors = []
        value = self.api._toFloatFromJSONOrNone(
            "density", {"density": 12345.6}, errors, minValue=0
        )

        self.assertAlmostEqual(12345.6, value)
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
