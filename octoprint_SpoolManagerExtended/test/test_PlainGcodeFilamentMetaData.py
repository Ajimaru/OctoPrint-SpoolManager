# coding=utf-8

# Tests for reading filament usage out of a plain gcode file's slicer comments.
#
# A file sent straight to a Bambu printer's storage arrives as plain `.gcode`: no local
# copy, no analysis metadata, and no 3mf container - observed on the A1mini with
# `printer:OctoScaleLEDCoverV1_PLA_8m6s.gcode`, which produced
# "calculating filament aborted because filament analysis metadata was missing" even
# though the file itself carries `; filament used [mm] = 42.31` in its footer.
#
# The multi-tool assertions use tool3, a value the bambu connector's analysis (which has
# none at all for plain gcode) and the moonraker connector's (which collapses everything
# onto tool0) cannot produce: if the parser silently stopped working, these fail rather
# than passing on some other source's value.
#
# Run with:  .venv/bin/python -m pytest octoprint_SpoolManagerExtended/test/test_PlainGcodeFilamentMetaData.py -v

import io
import logging
import os
import tempfile
import unittest
import zipfile

from octoprint_SpoolManagerExtended import SpoolmanagerPlugin

# real footer of the A1mini job, trimmed to the lines in play
A1MINI_SINGLE_TOOL_FOOTER = """
; EXECUTABLE_BLOCK_END

; filament used [mm] = 42.31
; filament used [cm3] = 0.10
; filament used [g] = 0.13
; total filament used [g] = 0.13
"""

# Orca slicing for the Snapmaker U1's slot 4: only the fourth tool is used
U1_MULTI_TOOL_FOOTER = """
; filament used [mm] = 0.00, 0.00, 0.00, 21872.80
; filament used [cm3] = 0.00, 0.00, 0.00, 52.60
"""


class FakePlugin(object):
    """
    Binds the parser straight off the production class, so these tests run against the
    real implementation rather than a copy of it.
    """

    _parseFilamentLengthsFromGcodeComments = (
        SpoolmanagerPlugin._parseFilamentLengthsFromGcodeComments
    )
    _parseFilamentCommentValues = SpoolmanagerPlugin._parseFilamentCommentValues
    _streamLength = SpoolmanagerPlugin._streamLength
    _resolvePrinterFilePath = SpoolmanagerPlugin._resolvePrinterFilePath
    _is3mfWithoutSliceData = SpoolmanagerPlugin._is3mfWithoutSliceData
    _findSlicedCompanionFile = SpoolmanagerPlugin._findSlicedCompanionFile
    FILAMENT_USED_MM_PATTERN = SpoolmanagerPlugin.FILAMENT_USED_MM_PATTERN
    FILAMENT_USED_CM3_PATTERN = SpoolmanagerPlugin.FILAMENT_USED_CM3_PATTERN

    def __init__(self):
        self._logger = logging.getLogger("test.plaingcodefilament")


class FakePrinterFile(object):
    def __init__(self, path, children=None):
        self.path = path
        self.children = children


class FakeConnection(object):
    """Printer storage as the bambu connector exposes it."""

    def __init__(self, paths, raises=False):
        self._paths = paths
        self._raises = raises

    def get_printer_files(self, *args, **kwargs):
        if self._raises:
            raise RuntimeError("printer offline")
        return [FakePrinterFile(p) for p in self._paths]


class TestPlainGcodeFilamentMetaData(unittest.TestCase):
    def setUp(self):
        self.plugin = FakePlugin()

    def _parse(self, content, **kwargs):
        return self.plugin._parseFilamentLengthsFromGcodeComments(
            io.BytesIO(content.encode("utf-8")), **kwargs
        )

    ############################################################### single tool

    def test_scalarUsageIsReadAsTool0(self):
        filament = self._parse(A1MINI_SINGLE_TOOL_FOOTER)

        self.assertIsNotNone(filament)
        self.assertEqual(["tool0"], list(filament.keys()))
        self.assertAlmostEqual(42.31, filament["tool0"]["length"], places=2)

    def test_volumeIsConvertedFromCm3ToMm3(self):
        filament = self._parse(A1MINI_SINGLE_TOOL_FOOTER)

        # metadata format expects mm3, the gcode comment reports cm3
        self.assertAlmostEqual(100.0, filament["tool0"]["volume"], places=2)

    def test_missingVolumeCommentStillYieldsLength(self):
        filament = self._parse("; filament used [mm] = 42.31\n")

        self.assertAlmostEqual(42.31, filament["tool0"]["length"], places=2)
        self.assertNotIn("volume", filament["tool0"])

    ############################################################### multi tool

    def test_perToolUsageKeepsTheToolTheJobActuallyUses(self):
        filament = self._parse(U1_MULTI_TOOL_FOOTER)

        self.assertIsNotNone(filament)
        self.assertIn("tool3", filament)
        self.assertAlmostEqual(21872.80, filament["tool3"]["length"], places=2)

    def test_unusedToolsAreAbsentRatherThanZero(self):
        # allowedToPrint() reads a missing tool as "this job does not use it" and a
        # present one as "in use" - reporting 0.0 here would warn about spools for
        # tools the job never touches
        filament = self._parse(U1_MULTI_TOOL_FOOTER)

        self.assertNotIn("tool0", filament)
        self.assertNotIn("tool1", filament)
        self.assertNotIn("tool2", filament)

    ############################################################### fallthrough

    def test_gcodeWithoutFilamentCommentYieldsNone(self):
        filament = self._parse("G1 X10 Y10\nM104 S200\n")

        self.assertIsNone(filament)

    def test_allZeroUsageYieldsNone(self):
        # nothing to book, and no tool may be reported as in use
        filament = self._parse("; filament used [mm] = 0.00, 0.00\n")

        self.assertIsNone(filament)

    def test_unparsableValueYieldsNone(self):
        filament = self._parse("; filament used [mm] = n/a\n")

        self.assertIsNone(filament)

    def test_truncatedFileYieldsNoneInsteadOfRaising(self):
        filament = self._parse("; filament used [mm] =")

        self.assertIsNone(filament)

    def test_binaryGarbageYieldsNoneInsteadOfRaising(self):
        filament = self.plugin._parseFilamentLengthsFromGcodeComments(
            io.BytesIO(b"\x00\x01\x02\xff\xfe")
        )

        self.assertIsNone(filament)

    ############################################################### file handling

    def test_readsFromAPathAsWellAsAStream(self):
        handle, path = tempfile.mkstemp(suffix=".gcode")
        try:
            with os.fdopen(handle, "w") as gcodeFile:
                gcodeFile.write(A1MINI_SINGLE_TOOL_FOOTER)

            filament = self.plugin._parseFilamentLengthsFromGcodeComments(path)

            self.assertAlmostEqual(42.31, filament["tool0"]["length"], places=2)
        finally:
            os.remove(path)

    def test_onlyTheTailIsRead(self):
        # printer-storage gcode runs to megabytes; the summary sits in the footer, so
        # the parser must not depend on reading the whole file
        padding = "G1 X10 Y10 E0.5\n" * 20000
        filament = self._parse(padding + A1MINI_SINGLE_TOOL_FOOTER)

        self.assertAlmostEqual(42.31, filament["tool0"]["length"], places=2)

    def test_commentBeyondTheTailWindowIsNotFound(self):
        # guards the tail optimisation itself: with a deliberately tiny window the
        # footer is out of reach, proving the window is what bounds the read
        padding = "G1 X10 Y10 E0.5\n" * 1000
        filament = self._parse(A1MINI_SINGLE_TOOL_FOOTER + padding, tailBytes=64)

        self.assertIsNone(filament)

    def test_lastSummaryWinsWhenAFileCarriesTwo(self):
        # a reprint may append a second block; the last one describes this job
        filament = self._parse(
            "; filament used [mm] = 1.00\n; filament used [mm] = 42.31\n"
        )

        self.assertAlmostEqual(42.31, filament["tool0"]["length"], places=2)


class TestPrinterFilePathResolution(unittest.TestCase):
    """
    The bambu connector reports a job path built from the printer's subtask_name with
    ".gcode.3mf" appended (connector.py _update_job_from_state()). For a job sent as
    plain gcode that names a file which is not on the SD card: the printer holds
    "OctoScaleLEDCoverV1_PLA_8m6s.gcode", the job says "...gcode.3mf", and the download
    fails. Observed on the A1mini on 2026-09-09.
    """

    A1MINI_STORAGE = [
        "Ghostship_Benchy_PLA_1h25m.gcode.3mf",
        "OctoScaleLEDCoverV1_PLA_8m6s.gcode",
        "rocket_PLA_16m17s.gcode.3mf",
    ]

    def setUp(self):
        self.plugin = FakePlugin()

    def test_reportedPathIsCorrectedToTheFileOnStorage(self):
        resolved = self.plugin._resolvePrinterFilePath(
            FakeConnection(self.A1MINI_STORAGE),
            "OctoScaleLEDCoverV1_PLA_8m6s.gcode.3mf",
        )

        self.assertEqual("OctoScaleLEDCoverV1_PLA_8m6s.gcode", resolved)

    def test_existingPathIsLeftAlone(self):
        # a real 3mf container must not be rewritten to a .gcode that does not exist
        resolved = self.plugin._resolvePrinterFilePath(
            FakeConnection(self.A1MINI_STORAGE), "Ghostship_Benchy_PLA_1h25m.gcode.3mf"
        )

        self.assertEqual("Ghostship_Benchy_PLA_1h25m.gcode.3mf", resolved)

    def test_unknownPathIsLeftAloneWhenNoAlternativeExists(self):
        resolved = self.plugin._resolvePrinterFilePath(
            FakeConnection(self.A1MINI_STORAGE), "SomethingElse.gcode.3mf"
        )

        self.assertEqual("SomethingElse.gcode.3mf", resolved)

    def test_pathInSubfolderIsFound(self):
        resolved = self.plugin._resolvePrinterFilePath(
            FakeConnection(["cache/A1+Toolbox_TPU_13m24s_plate_1.gcode"]),
            "cache/A1+Toolbox_TPU_13m24s_plate_1.gcode.3mf",
        )

        self.assertEqual("cache/A1+Toolbox_TPU_13m24s_plate_1.gcode", resolved)

    def test_unreachablePrinterLeavesPathUnchanged(self):
        # no listing is no reason to rewrite anything - let the download decide
        resolved = self.plugin._resolvePrinterFilePath(
            FakeConnection([], raises=True), "OctoScaleLEDCoverV1_PLA_8m6s.gcode.3mf"
        )

        self.assertEqual("OctoScaleLEDCoverV1_PLA_8m6s.gcode.3mf", resolved)

    def test_emptyListingLeavesPathUnchanged(self):
        resolved = self.plugin._resolvePrinterFilePath(
            FakeConnection([]), "OctoScaleLEDCoverV1_PLA_8m6s.gcode.3mf"
        )

        self.assertEqual("OctoScaleLEDCoverV1_PLA_8m6s.gcode.3mf", resolved)


class TestUnslicedProjectFileDetection(unittest.TestCase):
    """
    Bambu Studio / Orca leave the project file next to the sliced job on printer storage
    ("OctoScaleLEDCoverV1.3mf" beside "OctoScaleLEDCoverV1.gcode.3mf"). Both carry a
    Metadata/slice_info.config, but the project file's holds only a <header> - no <plate>,
    so no filament figures. Selecting it produced "missing metadata - wait for the
    uploaded file to be processed", which is wrong: there is nothing to wait for.
    Observed on the A1mini on 2026-09-09; the XML below is what those two files hold.
    """

    PROJECT_SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="OrcaSlicer-Version" value="2.4.2"/>
  </header>
</config>
"""

    SLICED_SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
  </header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="weight" value="0.13"/>
    <filament id="1" type="PLA" used_m="0.04" used_g="0.13"/>
  </plate>
</config>
"""

    def setUp(self):
        self.plugin = FakePlugin()

    def _make3mf(self, sliceInfo):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zipFile:
            if sliceInfo is not None:
                zipFile.writestr("Metadata/slice_info.config", sliceInfo)
            zipFile.writestr("3D/3dmodel.model", "<model/>")
        buffer.seek(0)
        return buffer

    def test_projectFileIsRecognisedAsUnsliced(self):
        self.assertTrue(
            self.plugin._is3mfWithoutSliceData(self._make3mf(self.PROJECT_SLICE_INFO))
        )

    def test_slicedFileIsNotFlagged(self):
        self.assertFalse(
            self.plugin._is3mfWithoutSliceData(self._make3mf(self.SLICED_SLICE_INFO))
        )

    def test_fileWithoutSliceInfoIsNotFlagged(self):
        # no slice_info.config at all is a different problem - do not claim it is unsliced
        self.assertFalse(self.plugin._is3mfWithoutSliceData(self._make3mf(None)))

    def test_nonZipIsNotFlagged(self):
        self.assertFalse(
            self.plugin._is3mfWithoutSliceData(
                io.BytesIO(b"; filament used [mm] = 1\n")
            )
        )

    ############################################################### companion lookup

    A1MINI_STORAGE = [
        "OctoScaleLEDCoverV1.3mf",
        "OctoScaleLEDCoverV1.gcode.3mf",
        "Ghostship_Benchy_PLA_1h25m.gcode.3mf",
    ]

    def test_slicedSiblingIsFound(self):
        companion = self.plugin._findSlicedCompanionFile(
            FakeConnection(self.A1MINI_STORAGE), "OctoScaleLEDCoverV1.3mf"
        )

        self.assertEqual("OctoScaleLEDCoverV1.gcode.3mf", companion)

    def test_noSiblingWhenOnlyTheProjectFileIsOnStorage(self):
        companion = self.plugin._findSlicedCompanionFile(
            FakeConnection(["OctoScaleLEDCoverV1.3mf"]), "OctoScaleLEDCoverV1.3mf"
        )

        self.assertIsNone(companion)

    def test_slicedFileIsNotItsOwnSibling(self):
        companion = self.plugin._findSlicedCompanionFile(
            FakeConnection(self.A1MINI_STORAGE), "OctoScaleLEDCoverV1.gcode.3mf"
        )

        self.assertIsNone(companion)

    def test_plainGcodeHasNoSibling(self):
        companion = self.plugin._findSlicedCompanionFile(
            FakeConnection(self.A1MINI_STORAGE), "OctoScaleLEDCoverV1_PLA_8m6s.gcode"
        )

        self.assertIsNone(companion)

    def test_deletedSiblingIsNoLongerNamed(self):
        # the sibling is looked up fresh on every call rather than remembered with the
        # file: naming a sliced file the user has since deleted sends them after nothing
        connection = FakeConnection(self.A1MINI_STORAGE)
        self.assertEqual(
            "OctoScaleLEDCoverV1.gcode.3mf",
            self.plugin._findSlicedCompanionFile(connection, "OctoScaleLEDCoverV1.3mf"),
        )

        connection._paths = ["OctoScaleLEDCoverV1.3mf"]

        self.assertIsNone(
            self.plugin._findSlicedCompanionFile(connection, "OctoScaleLEDCoverV1.3mf")
        )


if __name__ == "__main__":
    unittest.main()
