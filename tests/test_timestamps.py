"""Tests for timestamps in the outputs and for Office document properties."""

import csv
import io
import json
import os
import shutil
from datetime import datetime

from dupfinder.formatters import format_csv, format_json, format_table
from dupfinder.office import CoreProperties, is_office_file, read_core_properties
from dupfinder.scanner import DuplicateFinder
from tests.office_samples import make_docx

MTIME = 1_700_000_000


def _expected(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


class TestCoreProperties:
    """Test cases for reading properties stored inside Office documents."""

    def test_reads_modified_and_author(self, tmp_path):
        """Save time and last author come from docProps/core.xml."""
        path = make_docx(tmp_path / "a.docx", ["text"], modified="2026-05-06T07:08:09Z")

        assert read_core_properties(path) == CoreProperties("2026-05-06T07:08:09Z", "Ana")

    def test_non_office_file(self, tmp_path):
        """Other file types have no document properties."""
        path = tmp_path / "a.txt"
        path.write_text("text")

        assert not is_office_file(path)
        assert read_core_properties(path) == CoreProperties()

    def test_invalid_package(self, tmp_path):
        """A file that is not a valid package (e.g. password-protected) is tolerated."""
        path = tmp_path / "broken.docx"
        path.write_bytes(b"not a zip archive")

        assert read_core_properties(path) == CoreProperties()

    def test_package_without_core_properties(self, tmp_path):
        """A package without docProps/core.xml yields empty properties."""
        import zipfile

        path = tmp_path / "bare.xlsx"
        with zipfile.ZipFile(path, "w") as package:
            package.writestr("xl/workbook.xml", "<workbook/>")

        assert read_core_properties(path) == CoreProperties()


class TestTimestampOutput:
    """Test cases for timestamps reported by the formatters."""

    def _groups(self, tmp_path):
        a = make_docx(tmp_path / "a.docx", ["same"], modified="2026-05-06T07:08:09Z")
        b = tmp_path / "b.docx"
        shutil.copy(a, b)
        os.utime(a, (MTIME, MTIME))
        os.utime(b, (MTIME + 60, MTIME + 60))
        return a, b, DuplicateFinder().find_duplicates([tmp_path])

    def test_json_details(self, tmp_path):
        """JSON reports file system and document timestamps for each file."""
        a, b, groups = self._groups(tmp_path)

        details = json.loads(format_json(groups))[0]["details"]

        assert [d["path"] for d in details] == [str(a), str(b)]
        assert details[0]["modified"] == _expected(MTIME)
        assert details[1]["modified"] == _expected(MTIME + 60)
        assert details[0]["size"] == a.stat().st_size
        assert details[0]["document_modified"] == "2026-05-06T07:08:09Z"
        assert details[0]["document_last_modified_by"] == "Ana"

    def test_csv_columns(self, tmp_path):
        """CSV reports timestamps in dedicated columns."""
        _, _, groups = self._groups(tmp_path)

        rows = list(csv.DictReader(io.StringIO(format_csv(groups))))

        assert rows[0]["modified"] == _expected(MTIME)
        assert rows[1]["modified"] == _expected(MTIME + 60)
        assert rows[0]["document_modified"] == "2026-05-06T07:08:09Z"
        assert rows[0]["document_last_modified_by"] == "Ana"

    def test_table_lines(self, tmp_path):
        """The table shows the timestamps under each file."""
        _, _, groups = self._groups(tmp_path)

        table = format_table(groups)

        assert f"modified: {_expected(MTIME)}" in table
        assert "document saved: 2026-05-06T07:08:09Z by Ana" in table

    def test_table_shows_author_without_save_time(self, tmp_path):
        """The last author is shown even when the document has no save time."""
        import zipfile

        xml = (
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
            'metadata/core-properties"><cp:lastModifiedBy>Rui</cp:lastModifiedBy>'
            "</cp:coreProperties>"
        )
        a = tmp_path / "a.docx"
        with zipfile.ZipFile(a, "w") as package:
            package.writestr("docProps/core.xml", xml)
        shutil.copy(a, tmp_path / "b.docx")
        groups = DuplicateFinder().find_duplicates([tmp_path])

        assert "| document saved: by Rui" in format_table(groups)

    def test_plain_files_have_no_document_properties(self, tmp_path):
        """Non-Office files report only the file system timestamp."""
        (tmp_path / "a.txt").write_text("same")
        (tmp_path / "b.txt").write_text("same")
        groups = DuplicateFinder().find_duplicates([tmp_path])

        details = json.loads(format_json(groups))[0]["details"]

        assert details[0]["modified"] is not None
        assert details[0]["document_modified"] is None
        assert "document saved" not in format_table(groups)
