"""Tests for the detection of equivalent Office documents."""

import csv
import io
import json
import shutil
import sys
import zipfile

from dupfinder.cli import main
from dupfinder.equivalence import EquivalenceFinder, package_signature
from dupfinder.formatters import format_csv, format_json, format_table
from dupfinder.scanner import DuplicateFinder
from tests.office_samples import make_docx, make_pptx, make_xlsx

LABEL_1 = "ficheiro equivalente - nível 1 (validar)"


def _find(tmp_path, levels, **kwargs):
    finder = DuplicateFinder()
    duplicates = finder.find_duplicates([tmp_path])
    equivalents = EquivalenceFinder(levels, order_group=finder.order_group, **kwargs).find(
        finder.scanned_files, duplicates
    )
    return duplicates, equivalents


class TestPackageSignature:
    """Test cases for the level 1 signature."""

    def test_ignores_metadata_and_compression(self, tmp_path):
        """Different properties and compression give the same signature."""
        a = make_docx(tmp_path / "a.docx", ["Hello world"], author="Ana")
        b = make_docx(
            tmp_path / "b.docx",
            ["Hello world"],
            author="Rui",
            modified="2027-01-01T00:00:00Z",
            compression=zipfile.ZIP_STORED,
        )

        assert a.read_bytes() != b.read_bytes()
        assert package_signature(a) == package_signature(b)

    def test_content_change_changes_signature(self, tmp_path):
        """A different document body gives a different signature."""
        a = make_docx(tmp_path / "a.docx", ["Hello world"])
        b = make_docx(tmp_path / "b.docx", ["Hello there"])

        assert package_signature(a) != package_signature(b)

    def test_unreadable_package(self, tmp_path):
        """A file that is not a ZIP package has no signature."""
        path = tmp_path / "locked.docx"
        path.write_bytes(b"\xd0\xcf\x11\xe0 encrypted compound file")

        assert package_signature(path) is None


class TestLevelOne:
    """Test cases for level 1 groups."""

    def test_groups_all_supported_types(self, tmp_path):
        """Level 1 works for .docx, .xlsx and .pptx."""
        make_docx(tmp_path / "a.docx", ["text"], author="Ana")
        make_docx(tmp_path / "b.docx", ["text"], author="Rui")
        make_xlsx(tmp_path / "a.xlsx", {"S": [["x", 1]]}, author="Ana")
        make_xlsx(tmp_path / "b.xlsx", {"S": [["x", 1]]}, author="Rui")
        make_pptx(tmp_path / "a.pptx", [["title"]], author="Ana")
        make_pptx(tmp_path / "b.pptx", [["title"]], author="Rui")

        duplicates, equivalents = _find(tmp_path, {1})

        assert duplicates == {}
        assert [[f.name for f in g.files] for g in equivalents] == [
            ["a.docx", "b.docx"],
            ["a.pptx", "b.pptx"],
            ["a.xlsx", "b.xlsx"],
        ]
        assert {g.level for g in equivalents} == {1}
        assert equivalents[0].label == LABEL_1

    def test_not_searched_unless_requested(self, tmp_path):
        """No level requested means no equivalence search."""
        make_docx(tmp_path / "a.docx", ["text"], author="Ana")
        make_docx(tmp_path / "b.docx", ["text"], author="Rui")

        assert _find(tmp_path, set())[1] == []

    def test_exact_duplicates_are_not_repeated(self, tmp_path):
        """Exact duplicates are represented once in the equivalence results."""
        a = make_docx(tmp_path / "a.docx", ["text"], author="Ana")
        shutil.copy(a, tmp_path / "a_copy.docx")
        make_docx(tmp_path / "b.docx", ["text"], author="Rui")

        duplicates, equivalents = _find(tmp_path, {1})

        assert [[f.name for f in g] for g in duplicates.values()] == [["a.docx", "a_copy.docx"]]
        assert [[f.name for f in g.files] for g in equivalents] == [["a.docx", "b.docx"]]

    def test_only_exact_duplicates_yield_no_equivalents(self, tmp_path):
        """Byte-identical copies are duplicates, not equivalents."""
        a = make_docx(tmp_path / "a.docx", ["text"])
        shutil.copy(a, tmp_path / "b.docx")

        assert _find(tmp_path, {1})[1] == []

    def test_unreadable_and_legacy_files_are_skipped(self, tmp_path, caplog):
        """Password-protected, corrupt and legacy files are skipped and logged."""
        (tmp_path / "locked1.docx").write_bytes(b"encrypted one")
        (tmp_path / "locked2.docx").write_bytes(b"encrypted two")
        (tmp_path / "old.doc").write_bytes(b"legacy")

        with caplog.at_level("INFO"):
            _, equivalents = _find(tmp_path, {1})

        assert equivalents == []
        assert "not a readable Office package" in caplog.text
        assert "1 legacy Office files" in caplog.text


class TestEquivalentOutput:
    """Test cases for equivalent groups in the outputs."""

    def _results(self, tmp_path):
        make_docx(tmp_path / "a.docx", ["text"], author="Ana")
        make_docx(tmp_path / "b.docx", ["text"], author="Rui")
        return _find(tmp_path, {1})

    def test_json(self, tmp_path):
        """JSON marks equivalent groups with type, level and label."""
        duplicates, equivalents = self._results(tmp_path)

        data = json.loads(format_json(duplicates, None, equivalents))

        assert data[0]["match_type"] == "equivalent"
        assert data[0]["level"] == 1
        assert data[0]["label"] == LABEL_1
        assert [d["role"] for d in data[0]["details"]] == ["equivalent", "equivalent"]
        assert data[0]["details"][0]["modified"] is not None
        assert data[0]["details"][1]["document_last_modified_by"] == "Rui"

    def test_csv(self, tmp_path):
        """CSV marks equivalent rows with type, level and label."""
        duplicates, equivalents = self._results(tmp_path)

        rows = list(csv.DictReader(io.StringIO(format_csv(duplicates, None, equivalents))))

        assert [r["match_type"] for r in rows] == ["equivalent", "equivalent"]
        assert rows[0]["level"] == "1"
        assert rows[0]["label"] == LABEL_1
        assert rows[0]["modified"]

    def test_table(self, tmp_path):
        """The table shows the label and never marks an equivalent file as kept."""
        duplicates, equivalents = self._results(tmp_path)

        table = format_table(duplicates, None, equivalents)

        assert f"Equivalent group 1 (2 files): {LABEL_1}" in table
        assert "[keep]" not in table
        assert "Equivalent groups (to validate, never deleted): 1" in table


class TestNeverDeleted:
    """Equivalent files must never be deleted or hardlinked."""

    def _setup(self, tmp_path):
        a = make_docx(tmp_path / "a.docx", ["text"], author="Ana")
        a_copy = tmp_path / "a_copy.docx"
        shutil.copy(a, a_copy)
        b = make_docx(tmp_path / "b.docx", ["text"], author="Rui")
        return a, a_copy, b

    def test_delete_leaves_equivalents(self, tmp_path, monkeypatch, capsys):
        """--delete removes the exact duplicate and keeps the equivalent file."""
        a, a_copy, b = self._setup(tmp_path)

        monkeypatch.setattr(
            sys, "argv", ["dupfinder", str(tmp_path), "--equiv-package", "--delete"]
        )
        assert main() == 0

        assert a.exists() and b.exists()
        assert not a_copy.exists()
        assert LABEL_1 in capsys.readouterr().out

    def test_hardlink_leaves_equivalents(self, tmp_path, monkeypatch):
        """--hardlink links the exact duplicate and keeps the equivalent file apart."""
        a, a_copy, b = self._setup(tmp_path)

        monkeypatch.setattr(
            sys, "argv", ["dupfinder", str(tmp_path), "--equiv-package", "--hardlink"]
        )
        assert main() == 0

        assert a.stat().st_ino == a_copy.stat().st_ino
        assert b.stat().st_ino != a.stat().st_ino

    def test_delete_with_only_equivalents(self, tmp_path, monkeypatch, capsys):
        """With no exact duplicates, --delete removes nothing but still reports."""
        a = make_docx(tmp_path / "a.docx", ["text"], author="Ana")
        b = make_docx(tmp_path / "b.docx", ["text"], author="Rui")
        out_file = tmp_path / "out.json"

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "dupfinder",
                str(tmp_path),
                "--equiv-package",
                "--delete",
                "--output",
                "json",
                "--output-file",
                str(out_file),
            ],
        )
        assert main() == 0

        assert a.exists() and b.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data[0]["label"] == LABEL_1
