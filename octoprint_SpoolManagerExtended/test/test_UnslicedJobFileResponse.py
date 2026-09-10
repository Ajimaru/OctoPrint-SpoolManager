# coding=utf-8

# Tests that /allowedToPrint tells the frontend when the selected job is an unsliced
# project file.
#
# Bambu Studio / Orca leave the project file next to the sliced job on printer storage
# ("bracket.3mf", 28KB, beside "bracket.gcode.3mf", 44KB). The
# project file's Metadata/slice_info.config holds only a <header> - no <plate>, so no
# filament figures. Selecting it produced "missing metadata - wait for the uploaded file
# to be processed", which is wrong: there is nothing to wait for.
#
# These assertions cover the wiring rather than the detection (which
# test_PlainGcodeFilamentMetaData.py covers): allowed_to_print() assembles its own
# response dict and does not go through _evaluateRequiredWeight(), so a flag set during
# metadata reading only reaches the dialog if this endpoint forwards it. It did not, and
# the parser-level tests all passed regardless - observed on a Bambu instance.
#
# Run with:  .venv/bin/python -m pytest octoprint_SpoolManagerExtended/test/test_UnslicedJobFileResponse.py -v

import logging
import unittest

import flask
import peewee

from octoprint_SpoolManagerExtended.api.SpoolManagerAPI import SpoolManagerAPI
from octoprint_SpoolManagerExtended.common.SettingsKeys import SettingsKeys
from octoprint_SpoolManagerExtended.DatabaseManager import MODELS, DatabaseManager

PROJECT_FILE = "bracket.3mf"
SLICED_FILE = "bracket.gcode.3mf"


class FakeSettings(object):
    def __init__(self):
        self._values = {
            SettingsKeys.SETTINGS_KEY_SELECTED_SPOOLS_DATABASE_IDS: [],
            SettingsKeys.SETTINGS_KEY_WARN_IF_SPOOL_NOT_SELECTED: True,
            SettingsKeys.SETTINGS_KEY_WARN_IF_FILAMENT_NOT_ENOUGH: True,
            SettingsKeys.SETTINGS_KEY_REMINDER_SELECTING_SPOOL: True,
            SettingsKeys.SETTINGS_KEY_TOOL_OFFSET_ENABLED: True,
            SettingsKeys.SETTINGS_KEY_BED_OFFSET_ENABLED: True,
            SettingsKeys.SETTINGS_KEY_ENCLOSURE_OFFSET_ENABLED: True,
        }

    def get(self, keys):
        return self._values.get(keys[0])

    def get_boolean(self, keys):
        return self._values.get(keys[0])

    def set(self, keys, value):
        self._values[keys[0]] = value

    def save(self):
        pass


class FakePrinterProfileManager(object):
    def get_current_or_default(self):
        return {"extruder": {"count": 1}}


class FakePlugin(object):
    """Runs the real endpoint; only the metadata lookup is stood in for."""

    allowed_to_print = SpoolManagerAPI.allowed_to_print.__wrapped__
    loadSelectedSpools = SpoolManagerAPI.loadSelectedSpools

    def __init__(self, databaseManager, unslicedJobFile):
        self._databaseManager = databaseManager
        self._settings = FakeSettings()
        self._logger = logging.getLogger("test.unslicedjobfile")
        self._printer_profile_manager = FakePrinterProfileManager()
        self.metaDataFilamentLengths = []
        self._unslicedJobFile = unslicedJobFile

    def _readingFilamentMetaData(self):
        # an unsliced file yields no lengths, which is what makes metaDataMissing true
        return len(self.metaDataFilamentLengths) > 0

    def checkRemainingFilament(self, forToolIndex=None, shouldWarn=True):
        return {
            "metaDataMissing": True,
            "attributesMissing": False,
            "notEnough": False,
            "detailedSpoolResult": [],
        }


class TestUnslicedJobFileResponse(unittest.TestCase):
    def setUp(self):
        self.database = peewee.SqliteDatabase(":memory:")
        self.database.bind(MODELS)
        self.database.create_tables(MODELS)

        self.databaseManager = DatabaseManager(
            logging.getLogger("test.dbmanager"), False
        )
        self.databaseManager._database = self.database
        self.databaseManager._isConnected = True
        self.databaseManager.connectoToDatabase = lambda *a, **k: None
        self.databaseManager.closeDatabase = lambda *a, **k: None

        self.app = flask.Flask(__name__)

    def tearDown(self):
        self.database.drop_tables(MODELS)
        self.database.close()

    def _call(self, unslicedJobFile):
        plugin = FakePlugin(self.databaseManager, unslicedJobFile)
        with self.app.test_request_context():
            response = plugin.allowed_to_print()
        return flask.json.loads(response.get_data())

    def test_unslicedProjectFileIsReportedWithItsSlicedSibling(self):
        payload = self._call((PROJECT_FILE, SLICED_FILE))

        self.assertTrue(payload["metaDataMissing"])
        self.assertTrue(payload["jobFileNotSliced"])
        self.assertEqual(PROJECT_FILE, payload["jobFilePath"])
        # the dialog names this file, so the user can pick the right one
        self.assertEqual(SLICED_FILE, payload["slicedJobFilePath"])

    def test_unslicedFileWithoutSiblingStillFlagsTheCause(self):
        # nothing to point at, but "not sliced" still beats "wait for processing"
        payload = self._call((PROJECT_FILE, None))

        self.assertTrue(payload["jobFileNotSliced"])
        self.assertIsNone(payload["slicedJobFilePath"])

    def test_ordinaryMissingMetadataIsNotFlaggedAsUnsliced(self):
        # a file whose analysis is merely still running must keep the "wait" wording
        payload = self._call(None)

        self.assertTrue(payload["metaDataMissing"])
        self.assertFalse(payload["jobFileNotSliced"])
        self.assertIsNone(payload["jobFilePath"])
        self.assertIsNone(payload["slicedJobFilePath"])


if __name__ == "__main__":
    unittest.main()
