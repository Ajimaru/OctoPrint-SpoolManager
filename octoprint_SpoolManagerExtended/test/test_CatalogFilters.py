# coding=utf-8

import unittest
from unittest.mock import Mock

import flask

from octoprint_SpoolManagerExtended.api.SpoolManagerAPI import SpoolManagerAPI


class TestCatalogFilters(unittest.TestCase):
    def setUp(self):
        self.app = flask.Flask(__name__)
        self.api = object.__new__(SpoolManagerAPI)
        self.api._databaseManager = Mock()
        self.api._databaseManager.loadAllSpoolsByQuery.return_value = []
        self.api._databaseManager.countSpoolsByQuery.return_value = 0
        self.api._databaseManager.countAllSpools.return_value = 0
        self.api._databaseManager.loadCatalogVendors.return_value = ["Vendor"]
        self.api._databaseManager.loadCatalogMaterials.return_value = [
            "CustomFilament",
            "PLA",
        ]
        self.api._databaseManager.loadCatalogLabels.return_value = []
        self.api._databaseManager.loadCatalogColors.return_value = []
        self.api._databaseManager.loadSpoolTemplates.return_value = []
        self.api._databaseManager.isSchemeUpgradeNeeded.return_value = False

    def test_filterMaterialsOnlyContainsMaterialsInDatabase(self):
        with self.app.app_context():
            response = self.api._loadAllSpoolsByQueryResponse({})

        catalogs = response.get_json()["catalogs"]

        self.assertEqual(["CustomFilament", "PLA"], catalogs["filterMaterials"])
        self.assertIn("ABS", catalogs["materials"])
        self.assertIn("PLA", catalogs["materials"])
