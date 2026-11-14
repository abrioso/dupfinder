"""Tests for text extraction and for equivalence levels 2 and 3."""

import json
import shutil
import sys
import zipfile

import pytest

from dupfinder.cli import main
from dupfinder.equivalence import (
    EquivalenceFinder,
    sketch_similarity,
    text_sketch,
)
from dupfinder.formatters import format_csv, format_json, format_table
from dupfinder.office_text import extract_text
from dupfinder.scanner import DuplicateFinder
from tests.office_samples import core_xml, make_docx, make_pptx, make_xlsx

LABEL_2 = "ficheiro equivalente - nível 2 (validar)"
LABEL_3 = "ficheiro equivalente - nível 3 (validar)"

WORDS = [f"word{i}" for i in range(400)]


def _paragraphs(words):
    return [" ".join(words[i : i + 20]) for i in range(0, len(words), 20)]


def _find(tmp_path, levels, **kwargs):
    finder = DuplicateFinder()
    duplicates = finder.find_duplicates([tmp_path])
    equivalents = EquivalenceFinder(levels, order_group=finder.order_group, **kwargs).find(
        finder.scanned_files, duplicates
    )
    return duplicates, equivalents


def _names(groups):
    return [[f.name for f in g.files] for g in groups]


class TestExtractText:
    """Test cases for text extraction."""

    def test_docx_paragraphs(self, tmp_path):
        """Word text is one line per paragraph, whatever the formatting."""
        plain = make_docx(tmp_path / "a.docx", ["First  paragraph", "Second"])
        bold = make_docx(tmp_path / "b.docx", ["First paragraph", "Second"], bold=True)

        assert extract_text(plain) == "First paragraph\nSecond"
        assert extract_text(bold) == extract_text(plain)

    def test_docx_split_runs_and_notes(self, tmp_path):
        """Runs of a paragraph are joined; tracked deletions are ignored; notes count."""
        w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        path = tmp_path / "runs.docx"
        with zipfile.ZipFile(path, "w") as package:
            package.writestr(
                "word/document.xml",
                f'<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>Hel</w:t></w:r>'
                "<w:r><w:t>lo</w:t><w:tab/><w:t>world</w:t></w:r>"
                "<w:del><w:r><w:delText>gone</w:delText></w:r></w:del></w:p>"
                "</w:body></w:document>",
            )
            package.writestr(
                "word/footnotes.xml",
                f'<w:footnotes xmlns:w="{w}"><w:footnote><w:p><w:r><w:t>A note</w:t></w:r>'
                "</w:p></w:footnote></w:footnotes>",
            )

        assert extract_text(path) == "Hello world\nA note"

    def test_xlsx_rows_formulas_and_sheet_order(self, tmp_path):
        """Workbook text follows sheet order and reports formulas, not cached values."""
        path = make_xlsx(
            tmp_path / "a.xlsx",
            {"Budget": [["Item", "Cost"], ["Laptop", 1200], ["Total", "=SUM(B2:B2)"]]},
        )

        assert extract_text(path) == "# Budget\nItem Cost\nLaptop 1200\nTotal =SUM(B2:B2)"

    def test_xlsx_same_values_different_formulas_differ(self, tmp_path):
        """A formula and a typed value are different text."""
        formula = make_xlsx(tmp_path / "a.xlsx", {"S": [["Total", "=1+1"]]})
        value = make_xlsx(tmp_path / "b.xlsx", {"S": [["Total", 2]]})

        assert extract_text(formula) != extract_text(value)

    def test_xlsx_inline_strings_and_fallback_order(self, tmp_path):
        """Inline strings are read and sheets are found without a workbook index."""
        s = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        path = tmp_path / "inline.xlsx"

        def sheet(text):
            return (
                f'<worksheet xmlns="{s}"><sheetData><row r="1"><c r="A1" t="inlineStr">'
                f"<is><t>{text}</t></is></c></row></sheetData></worksheet>"
            )

        with zipfile.ZipFile(path, "w") as package:
            package.writestr("xl/worksheets/sheet10.xml", sheet("ten"))
            package.writestr("xl/worksheets/sheet2.xml", sheet("two"))

        assert extract_text(path) == "#\ntwo\n#\nten"

    def test_xlsx_booleans_are_not_numbers(self, tmp_path):
        """A boolean cell is TRUE/FALSE, not the number 1/0."""
        s = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

        def book(path, cell):
            with zipfile.ZipFile(path, "w") as package:
                package.writestr(
                    "xl/worksheets/sheet1.xml",
                    f'<worksheet xmlns="{s}"><sheetData><row r="1">{cell}</row></sheetData>'
                    "</worksheet>",
                )
            return path

        boolean = book(tmp_path / "a.xlsx", '<c r="A1" t="b"><v>1</v></c>')
        false = book(tmp_path / "b.xlsx", '<c r="A1" t="b"><v>0</v></c>')
        number = book(tmp_path / "c.xlsx", '<c r="A1"><v>1</v></c>')

        assert extract_text(boolean) == "#\nTRUE"
        assert extract_text(false) == "#\nFALSE"
        assert extract_text(number) == "#\n1"

    def test_xlsx_shared_formula_ids_do_not_matter(self, tmp_path):
        """Shared formulas with different group ids but the same master are the same text."""
        s = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

        def book(path, group, master="A1*2"):
            with zipfile.ZipFile(path, "w") as package:
                package.writestr(
                    "xl/worksheets/sheet1.xml",
                    f'<worksheet xmlns="{s}"><sheetData>'
                    f'<row r="1"><c r="B1"><f t="shared" ref="B1:B2" si="{group}">{master}</f>'
                    f'<v>2</v></c></row><row r="2"><c r="B2"><f t="shared" si="{group}"/>'
                    "<v>4</v></c></row></sheetData></worksheet>",
                )
            return path

        first = book(tmp_path / "a.xlsx", 0)
        renumbered = book(tmp_path / "b.xlsx", 5)
        different = book(tmp_path / "c.xlsx", 0, master="A1*3")

        assert extract_text(first) == "#\n=A1*2\n=shared(A1*2)"
        assert extract_text(renumbered) == extract_text(first)
        assert extract_text(different) != extract_text(first)

    def test_text_starting_with_hash_is_content(self, tmp_path):
        """Documents whose every line starts with '# ' still have text."""
        doc = make_docx(tmp_path / "a.docx", ["# Introduction", "# Summary"])
        deck = make_pptx(tmp_path / "a.pptx", [["# Title"]])
        book = make_xlsx(tmp_path / "a.xlsx", {"S": [["# note"]]})

        assert extract_text(doc) == "# Introduction\n# Summary"
        assert extract_text(deck) == "# Title"
        assert extract_text(book) == "# S\n# note"

    def test_pptx_slide_order(self, tmp_path):
        """Presentation text follows the slide order of the presentation part."""
        path = make_pptx(tmp_path / "a.pptx", [["Title", "Subtitle"], ["Second slide"]])

        assert extract_text(path) == "Title\nSubtitle\nSecond slide"

    def test_pptx_notes_follow_slide_order(self, tmp_path):
        """Speaker notes are ordered by their slides, not by their part names."""
        rel = "http://schemas.openxmlformats.org/package/2006/relationships"
        a_ns = "http://schemas.openxmlformats.org/drawingml/2006/main"

        def deck(path, note_of_first, note_of_second):
            make_pptx(path, [["First"], ["Second"]])
            with zipfile.ZipFile(path, "a") as package:
                for slide, (number, text) in enumerate([note_of_first, note_of_second], 1):
                    package.writestr(
                        f"ppt/notesSlides/notesSlide{number}.xml",
                        f'<p:notes xmlns:p="x" xmlns:a="{a_ns}"><a:p><a:r><a:t>{text}</a:t>'
                        "</a:r></a:p></p:notes>",
                    )
                    package.writestr(
                        f"ppt/slides/_rels/slide{slide}.xml.rels",
                        f'<Relationships xmlns="{rel}"><Relationship Id="rId1" '
                        f'Type="notesSlide" Target="../notesSlides/notesSlide{number}.xml"/>'
                        "</Relationships>",
                    )
            return path

        natural = deck(tmp_path / "a.pptx", (1, "note one"), (2, "note two"))
        swapped = deck(tmp_path / "b.pptx", (2, "note one"), (1, "note two"))

        assert extract_text(natural) == "First\nSecond\nnote one\nnote two"
        assert extract_text(swapped) == extract_text(natural)

    def test_no_text(self, tmp_path):
        """Documents without text, other types and broken files yield None."""
        empty_doc = make_docx(tmp_path / "empty.docx", [])
        empty_book = make_xlsx(tmp_path / "empty.xlsx", {"Sheet1": []})
        text_file = tmp_path / "a.txt"
        text_file.write_text("text")
        broken = tmp_path / "broken.pptx"
        broken.write_bytes(b"not a zip")
        bad_xml = tmp_path / "bad.docx"
        with zipfile.ZipFile(bad_xml, "w") as package:
            package.writestr("word/document.xml", "<w:document>")

        assert extract_text(empty_doc) is None
        assert extract_text(empty_book) is None
        assert extract_text(text_file) is None
        assert extract_text(broken) is None
        assert extract_text(bad_xml) is None

    def test_corrupt_compressed_parts_are_skipped(self, tmp_path):
        """Damaged compressed streams skip the document instead of raising."""
        from dupfinder.equivalence import package_signature

        def damage(path, part):
            data = bytearray(path.read_bytes())
            start = data.index(part.encode()) + len(part)
            data[start : start + 8] = b"\xff" * 8
            path.write_bytes(bytes(data))
            return path

        body = make_docx(tmp_path / "body.docx", _paragraphs(WORDS))
        damage(body, "word/document.xml")
        descriptor = tmp_path / "descriptor.docx"
        with zipfile.ZipFile(descriptor, "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr("word/document.xml", "<document/>")
            package.writestr("_rels/.rels", "<Relationships>" + " " * 2000 + "</Relationships>")
        damage(descriptor, "_rels/.rels")

        assert extract_text(body) is None
        assert package_signature(descriptor) is None
        assert _find(tmp_path, {1, 2, 3})[1] == []


class TestSketch:
    """Test cases for the similarity sketch."""

    def test_identical_and_disjoint(self):
        """Identical texts score 1 and unrelated texts score 0."""
        a = text_sketch(" ".join(WORDS))
        b = text_sketch(" ".join(f"other{i}" for i in range(400)))

        assert sketch_similarity(a, a) == 1.0
        assert sketch_similarity(a, b) == 0.0
        assert sketch_similarity(a, ()) == 0.0

    def test_exact_for_small_texts(self):
        """With few shingles the estimate equals the true Jaccard similarity."""
        a = text_sketch("one two three four five six")  # 3 shingles
        b = text_sketch("one two three four five seven")  # 3 shingles, 2 shared

        assert sketch_similarity(a, b) == pytest.approx(2 / 4)

    def test_short_and_empty_texts(self):
        """Texts shorter than a shingle still get a sketch; texts without words do not."""
        assert len(text_sketch("only two")) == 1
        assert text_sketch("... !!!") == ()

    def test_case_and_punctuation_ignored(self):
        """Case and punctuation do not change the sketch."""
        assert text_sketch("Hello, World: again and again") == text_sketch(
            "hello world again and again"
        )

    def test_estimate_close_to_true_value(self):
        """For long texts the estimate stays close to the true similarity."""
        words = [f"w{i}" for i in range(5000)]
        changed = list(words)
        for i in range(0, 5000, 100):
            changed[i] = f"x{i}"
        shingles_a = {tuple(words[i : i + 4]) for i in range(4997)}
        shingles_b = {tuple(changed[i : i + 4]) for i in range(4997)}
        true_value = len(shingles_a & shingles_b) / len(shingles_a | shingles_b)

        estimate = sketch_similarity(text_sketch(" ".join(words)), text_sketch(" ".join(changed)))

        assert estimate == pytest.approx(true_value, abs=0.08)


class TestLevelTwo:
    """Test cases for level 2 groups (same text)."""

    def test_same_text_different_formatting(self, tmp_path):
        """Formatting changes are level 2 for every supported type."""
        make_docx(tmp_path / "a.docx", ["Same text"])
        make_docx(tmp_path / "b.docx", ["Same text"], bold=True)
        make_xlsx(tmp_path / "a.xlsx", {"S": [["x", 1]]})
        make_xlsx(tmp_path / "b.xlsx", {"S": [["x", 1]]}, style=3)
        make_pptx(tmp_path / "a.pptx", [["Title"]])
        make_pptx(tmp_path / "b.pptx", [["Title"]], size=2400)

        _, equivalents = _find(tmp_path, {1, 2})

        assert _names(equivalents) == [
            ["a.docx", "b.docx"],
            ["a.pptx", "b.pptx"],
            ["a.xlsx", "b.xlsx"],
        ]
        assert {g.level for g in equivalents} == {2}
        assert equivalents[0].label == LABEL_2

    def test_different_types_are_not_grouped(self, tmp_path):
        """A document and a presentation with the same text are not equivalent."""
        make_docx(tmp_path / "a.docx", ["Same text"])
        make_pptx(tmp_path / "a.pptx", [["Same text"]])

        assert _find(tmp_path, {2, 3})[1] == []

    def test_pair_reported_at_lowest_level_only(self, tmp_path):
        """Each pair appears once, at the lowest level where it matches."""
        make_docx(tmp_path / "a.docx", ["Same text"], author="Ana")
        make_docx(tmp_path / "b_meta.docx", ["Same text"], author="Rui")
        make_docx(tmp_path / "c_bold.docx", ["Same text"], bold=True)

        _, equivalents = _find(tmp_path, {1, 2, 3})

        assert [(g.level, [f.name for f in g.files]) for g in equivalents] == [
            (1, ["a.docx", "b_meta.docx"]),
            (2, ["a.docx", "c_bold.docx"]),
        ]

    def test_levels_are_independent(self, tmp_path):
        """Only the requested levels are searched."""
        make_docx(tmp_path / "a.docx", ["Same text"], author="Ana")
        make_docx(tmp_path / "b.docx", ["Same text"], author="Rui")

        _, only_two = _find(tmp_path, {2})

        assert [(g.level, [f.name for f in g.files]) for g in only_two] == [
            (2, ["a.docx", "b.docx"])
        ]

    def test_documents_without_text_are_not_grouped(self, tmp_path):
        """Documents with no text are not equivalent to each other."""
        make_docx(tmp_path / "a.docx", [])
        make_docx(tmp_path / "b.docx", [], bold=True, author="Rui")

        assert _find(tmp_path, {2, 3})[1] == []


class TestLevelThree:
    """Test cases for level 3 groups (similar text)."""

    def _versions(self, tmp_path):
        v2 = list(WORDS)
        v2[100] = "changed"
        v3 = list(v2)
        v3[300] = "edited"
        make_docx(tmp_path / "report_v1.docx", _paragraphs(WORDS))
        make_docx(tmp_path / "report_v2.docx", _paragraphs(v2))
        make_docx(tmp_path / "report_v3.docx", _paragraphs(v3))
        make_docx(tmp_path / "unrelated.docx", _paragraphs([f"other{i}" for i in range(400)]))

    def test_versions_are_grouped(self, tmp_path):
        """Successive versions form one group; unrelated documents stay out."""
        self._versions(tmp_path)

        _, equivalents = _find(tmp_path, {1, 2, 3})

        assert _names(equivalents) == [["report_v1.docx", "report_v2.docx", "report_v3.docx"]]
        group = equivalents[0]
        assert group.level == 3
        assert group.label == LABEL_3
        assert group.similarity[group.files[0]] == 1.0
        assert 0.9 <= group.similarity[group.files[1]] < 1.0

    def test_threshold(self, tmp_path):
        """A stricter threshold drops pairs below it."""
        half = WORDS[:200] + [f"new{i}" for i in range(200)]
        make_docx(tmp_path / "a.docx", _paragraphs(WORDS))
        make_docx(tmp_path / "b.docx", _paragraphs(half))

        assert _find(tmp_path, {3}, similarity_threshold=0.9)[1] == []
        assert _names(_find(tmp_path, {3}, similarity_threshold=0.3)[1]) == [["a.docx", "b.docx"]]

    def test_widely_shared_text_is_still_grouped(self, tmp_path, monkeypatch):
        """Shingles shared by more documents than the cap do not hide a group."""
        monkeypatch.setattr("dupfinder.equivalence.MAX_SHARED_DOCUMENTS", 2)
        v2 = list(WORDS)
        v2[100] = "changed"
        v3 = list(WORDS)
        v3[200] = "edited"
        v4 = list(WORDS)
        v4[300] = "revised"
        make_docx(tmp_path / "a.docx", _paragraphs(WORDS))
        make_docx(tmp_path / "b.docx", _paragraphs(WORDS), bold=True)
        make_docx(tmp_path / "c.docx", _paragraphs(WORDS), author="Rui")
        make_docx(tmp_path / "d.docx", _paragraphs(v2))
        make_docx(tmp_path / "e.docx", _paragraphs(v3))
        make_docx(tmp_path / "f.docx", _paragraphs(v4))

        _, equivalents = _find(tmp_path, {3})

        assert _names(equivalents) == [["a.docx", "b.docx", "c.docx", "d.docx", "e.docx", "f.docx"]]
        assert equivalents[0].similarity[tmp_path / "b.docx"] == 1.0

    def test_invalid_threshold(self):
        """Thresholds outside (0, 1] are rejected."""
        for value in (0, -0.1, 1.5):
            with pytest.raises(ValueError):
                EquivalenceFinder({3}, similarity_threshold=value)

    def test_spreadsheets_and_presentations(self, tmp_path):
        """Level 3 also works for workbooks and presentations."""
        rows = [[f"item{i}", f"desc{i}", i] for i in range(100)]
        changed = [list(r) for r in rows]
        changed[50][1] = "updated"
        make_xlsx(tmp_path / "a.xlsx", {"Data": rows})
        make_xlsx(tmp_path / "b.xlsx", {"Data": changed})
        slides = [[f"slide {i} title", f"point one of slide {i}"] for i in range(40)]
        edited = [list(s) for s in slides]
        edited[20][0] = "a new title"
        make_pptx(tmp_path / "a.pptx", slides)
        make_pptx(tmp_path / "b.pptx", edited)

        _, equivalents = _find(tmp_path, {3})

        assert _names(equivalents) == [["a.pptx", "b.pptx"], ["a.xlsx", "b.xlsx"]]

    def test_output_includes_similarity(self, tmp_path):
        """Similarity to the first file is reported in every format."""
        self._versions(tmp_path)
        duplicates, equivalents = _find(tmp_path, {3})

        data = json.loads(format_json(duplicates, None, equivalents))
        assert data[0]["label"] == LABEL_3
        assert data[0]["details"][0]["similarity"] == 1.0
        assert data[0]["details"][1]["similarity"] < 1.0

        csv_lines = format_csv(duplicates, None, equivalents).splitlines()
        assert csv_lines[1].endswith(f",equivalent,3,{LABEL_3},1.00")

        table = format_table(duplicates, None, equivalents)
        assert f"Equivalent group 1 (3 files): {LABEL_3}" in table
        assert "(similarity 1.00)" in table


class TestCLI:
    """Test cases for the command-line options of levels 2 and 3."""

    def test_all_levels_never_delete(self, tmp_path, monkeypatch, capsys):
        """--delete with every level removes only the exact duplicate."""
        v2 = list(WORDS)
        v2[100] = "changed"
        original = make_docx(tmp_path / "a.docx", _paragraphs(WORDS), author="Ana")
        exact = tmp_path / "a_exact.docx"
        shutil.copy(original, exact)
        level1 = make_docx(tmp_path / "b_meta.docx", _paragraphs(WORDS), author="Rui")
        level2 = make_docx(tmp_path / "c_bold.docx", _paragraphs(WORDS), bold=True)
        level3 = make_docx(tmp_path / "d_v2.docx", _paragraphs(v2))

        monkeypatch.setattr(
            sys,
            "argv",
            [
                "dupfinder",
                str(tmp_path),
                "--equiv-package",
                "--equiv-text",
                "--equiv-similar",
                "--delete",
                "--output",
                "json",
            ],
        )
        assert main() == 0

        assert not exact.exists()
        assert all(f.exists() for f in (original, level1, level2, level3))
        data = json.loads(capsys.readouterr().out)
        assert [(g["match_type"], g.get("level")) for g in data] == [
            ("exact", None),
            ("equivalent", 1),
            ("equivalent", 2),
            ("equivalent", 3),
        ]

    def test_invalid_threshold_rejected(self, tmp_path, monkeypatch):
        """An out-of-range --similarity-threshold is an error."""
        monkeypatch.setattr(
            sys,
            "argv",
            ["dupfinder", str(tmp_path), "--equiv-similar", "--similarity-threshold", "2"],
        )
        assert main() == 1

    def test_core_properties_part_is_ignored_by_text(self, tmp_path):
        """Document properties never count as text."""
        path = tmp_path / "props.docx"
        with zipfile.ZipFile(path, "w") as package:
            package.writestr("docProps/core.xml", core_xml())
            package.writestr("word/document.xml", "<document/>")

        assert extract_text(path) is None
