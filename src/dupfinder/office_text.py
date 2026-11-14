"""Text extraction from Office Open XML documents (.docx, .xlsx, .pptx).

Only the standard library is used. Text is returned as normalized lines (one per
paragraph or spreadsheet row) so that formatting changes do not affect it.
"""

import io
import logging
import posixpath
import re
import unicodedata
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree

from dupfinder.office import PACKAGE_ERRORS, XML_ERRORS, read_part

logger = logging.getLogger(__name__)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

# Marks structure (sheet names, formulas, header and footer boundaries) in the extracted
# text. XML 1.0 content cannot contain this character and it is stripped from content
# anyway, so document text can never be mistaken for structure.
STRUCTURE = "\x01"

_HEADER_FOOTER_REFERENCES = {f"{_W}headerReference": "header", f"{_W}footerReference": "footer"}
_NOTE_REFERENCES = {f"{_W}footnoteReference": "footnote", f"{_W}endnoteReference": "endnote"}
_NOTE_PARTS = {
    "footnote": ("word/footnotes.xml", f"{_W}footnote"),
    "endnote": ("word/endnotes.xml", f"{_W}endnote"),
}
# Notes that Word generates to draw separators; they are not document text
_SEPARATOR_NOTE_TYPES = {"separator", "continuationSeparator", "continuationNotice"}
_WORD_BREAKS = {f"{_W}tab", f"{_W}br", f"{_W}cr"}
_CELL_COLUMN = re.compile(r"([A-Za-z]+)\d*")

_WHITESPACE = re.compile(r"\s+")
_NUMBER = re.compile(r"(\d+)")


def _natural_key(name: str) -> list[int | str]:
    """Sort key ordering 'slide2' before 'slide10'."""
    return [int(piece) if piece.isdigit() else piece for piece in _NUMBER.split(name)]


def _collapse(line: str) -> str:
    """Normalize the Unicode form and the whitespace of a line, keeping structure marks."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", line)).strip()


def _normalize(line: str) -> str:
    """Normalize a line of document content, which can never carry structure marks."""
    return _collapse(line.replace(STRUCTURE, ""))


def _paragraphs(
    data: bytes,
    text_tag: str,
    paragraph_tag: str,
    break_tags: set[str],
    references: list[tuple[str, str, str]] | None = None,
    notes: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """Extract one line per paragraph from a WordprocessingML or DrawingML part.

    Args:
        data: XML content of the part
        text_tag: Qualified tag of text runs
        paragraph_tag: Qualified tag of paragraphs
        break_tags: Qualified tags rendered as a space (tabs, line breaks)
        references: When given, receives the header and footer references found, in
            document order, as (kind, type, relationship id)
        notes: When given, footnote and endnote texts by kind and id; each one is placed
            where the body refers to it and removed from the mapping

    Returns:
        Normalized, non-empty text of each paragraph, in document order
    """
    lines: list[str] = []
    buffer: list[str] = []
    for _, element in ElementTree.iterparse(io.BytesIO(data), events=("end",)):
        tag = element.tag
        if tag == text_tag:
            buffer.append((element.text or "").replace(STRUCTURE, ""))
        elif tag in break_tags:
            buffer.append(" ")
        elif tag == paragraph_tag:
            lines.append(_collapse("".join(buffer)))
            buffer.clear()
            element.clear()
        elif notes is not None and tag in _NOTE_REFERENCES:
            kind = _NOTE_REFERENCES[tag]
            text = notes[kind].pop(element.get(f"{_W}id", ""), "")
            if text:
                buffer.append(f" {STRUCTURE}{kind}({text}) ")
        elif references is not None and tag in _HEADER_FOOTER_REFERENCES:
            references.append(
                (
                    _HEADER_FOOTER_REFERENCES[tag],
                    element.get(f"{_W}type", ""),
                    element.get(f"{_R}id", ""),
                )
            )
    if buffer:
        lines.append(_collapse("".join(buffer)))
    return [line for line in lines if line]


def _relationships(package: zipfile.ZipFile, part: str) -> dict[str, str]:
    """Read the relationships of a part as a mapping from id to target part name.

    Args:
        package: Open Office document
        part: Part whose relationships are wanted (e.g. 'xl/workbook.xml')

    Returns:
        Mapping from relationship id to the resolved part name
    """
    directory, filename = posixpath.split(part)
    data = read_part(package, posixpath.join(directory, "_rels", f"{filename}.rels"))
    if data is None:
        return {}
    targets = {}
    for relationship in ElementTree.fromstring(data).iter(f"{_REL}Relationship"):
        if relationship.get("TargetMode") == "External":
            continue
        target = relationship.get("Target", "")
        if target.startswith("/"):
            resolved = target.lstrip("/")
        else:
            resolved = posixpath.normpath(posixpath.join(directory, target))
        targets[relationship.get("Id", "")] = resolved
    return targets


def _ordered_parts(
    package: zipfile.ZipFile, index_part: str, item_tag: str, fallback: re.Pattern[str]
) -> list[tuple[str, str]]:
    """List the sheets or slides of a document in the order the user sees them.

    Args:
        package: Open Office document
        index_part: Part listing the items ('xl/workbook.xml' or 'ppt/presentation.xml')
        item_tag: Qualified tag of the items in the index part
        fallback: Pattern of part names used when the index cannot be resolved

    Returns:
        (name, part name) pairs; the name is empty when the item has none
    """
    names = set(package.namelist())
    ordered: list[tuple[str, str]] = []
    data = read_part(package, index_part)
    if data is not None:
        targets = _relationships(package, index_part)
        for item in ElementTree.fromstring(data).iter(item_tag):
            part = targets.get(item.get(f"{_R}id", ""))
            if part in names:
                ordered.append((item.get("name", ""), part))
    if not ordered:
        ordered = [("", n) for n in sorted(names, key=_natural_key) if fallback.fullmatch(n)]
    return ordered


def _docx_notes(package: zipfile.ZipFile, kind: str) -> dict[str, str]:
    """Read the footnotes or endnotes of a Word document.

    Args:
        package: Open Office document
        kind: 'footnote' or 'endnote'

    Returns:
        Text of each note by id, in part order, without the separator notes
    """
    part, note_tag = _NOTE_PARTS[kind]
    data = read_part(package, part)
    if data is None:
        return {}

    notes: dict[str, str] = {}
    lines: list[str] = []
    buffer: list[str] = []
    for _, element in ElementTree.iterparse(io.BytesIO(data), events=("end",)):
        tag = element.tag
        if tag == f"{_W}t":
            buffer.append((element.text or "").replace(STRUCTURE, ""))
        elif tag in _WORD_BREAKS:
            buffer.append(" ")
        elif tag == f"{_W}p":
            lines.append(_collapse("".join(buffer)))
            buffer.clear()
        elif tag == note_tag:
            text = " ".join(line for line in lines if line)
            if text and element.get(f"{_W}type") not in _SEPARATOR_NOTE_TYPES:
                notes[element.get(f"{_W}id", "")] = text
            lines.clear()
            element.clear()
    return notes


def _docx_lines(package: zipfile.ZipFile) -> Iterator[str]:
    """Yield the paragraphs of a Word document, including notes, headers and footers.

    Footnotes and endnotes are placed where the body refers to them, and headers and
    footers follow the section references, so the same parts attached to different
    passages or sections give different text. Header and footer parts that no section
    references are not rendered by Word and are left out.
    """
    tags = (f"{_W}t", f"{_W}p", _WORD_BREAKS)
    references: list[tuple[str, str, str]] = []
    notes = {kind: _docx_notes(package, kind) for kind in _NOTE_PARTS}
    data = read_part(package, "word/document.xml")
    if data is not None:
        yield from _paragraphs(data, *tags, references=references, notes=notes)

    # Notes the body never refers to are kept, after the body, so no text is lost
    for remaining in notes.values():
        yield from remaining.values()

    targets = _relationships(package, "word/document.xml") if references else {}
    for kind, reference_type, relationship_id in references:
        data = read_part(package, targets.get(relationship_id, ""))
        lines = _paragraphs(data, *tags) if data is not None else []
        if lines:
            yield f"{STRUCTURE}{kind} {reference_type}"
            yield from lines


def _shared_strings(package: zipfile.ZipFile) -> list[str]:
    """Read the shared strings table of a workbook."""
    data = read_part(package, "xl/sharedStrings.xml")
    if data is None:
        return []
    strings = []
    for _, element in ElementTree.iterparse(io.BytesIO(data), events=("end",)):
        if element.tag == f"{_S}si":
            # Phonetic runs (rPh) are annotations, not cell text
            runs = element.findall(f"{_S}t") + element.findall(f"{_S}r/{_S}t")
            strings.append("".join(t.text or "" for t in runs))
            element.clear()
    return strings


def _cell_value(cell: ElementTree.Element, shared: list[str], formulas: dict[str, str]) -> str:
    """Return the text of a worksheet cell.

    Formulas are reported instead of their cached results, so that two workbooks with the
    same visible values but different formulas are not considered to have the same text.

    Args:
        cell: Worksheet cell element
        shared: Shared strings table of the workbook
        formulas: Text of the shared formulas seen so far in the sheet, by group id;
            updated when the cell is the master of a shared formula

    Returns:
        Normalized text of the cell; formulas carry the structure marker so that a
        formula and a literal string starting with '=' stay different
    """
    formula = cell.find(f"{_S}f")
    if formula is not None:
        group = formula.get("si") if formula.get("t") == "shared" else None
        if formula.text:
            if group is not None:
                formulas[group] = formula.text
            return f"{STRUCTURE}={_normalize(formula.text)}"
        # Follower of a shared formula: refer to the master's text, because the group
        # identifier is an arbitrary number that differs between saves
        return f"{STRUCTURE}=shared({_normalize(formulas.get(group or '', ''))})"
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return _normalize("".join(t.text or "" for t in cell.iter(f"{_S}t")))
    value = cell.find(f"{_S}v")
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        try:
            return _normalize(shared[int(value.text)])
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        # Booleans are stored as 1/0 but are not the numbers 1 and 0
        return "TRUE" if value.text.strip() == "1" else "FALSE"
    return _normalize(value.text)


def _column_index(reference: str | None) -> int | None:
    """Convert a cell reference such as 'C7' into a zero-based column index.

    Args:
        reference: Cell reference, or None when the cell has none

    Returns:
        Column index, or None when the reference cannot be read
    """
    match = _CELL_COLUMN.fullmatch(reference or "")
    if match is None:
        return None
    index = 0
    for letter in match.group(1).upper():
        index = index * 26 + ord(letter) - ord("A") + 1
    return index - 1


def _xlsx_lines(package: zipfile.ZipFile) -> Iterator[str]:
    """Yield the non-empty rows of a workbook, each sheet preceded by its name.

    Sheet names are only emitted for sheets with content, so a workbook of empty sheets
    yields nothing. Sheet names carry the structure marker and the cells of a row are
    separated by tabs, so cell text cannot imitate a sheet boundary or a cell boundary.

    Positions are kept: empty cells before a value leave empty fields, and a row that does
    not directly follow the previous one is preceded by a mark with its number. Positions
    are relative, so inserting a row changes one mark instead of every following row.
    """
    shared = _shared_strings(package)
    sheets = _ordered_parts(
        package, "xl/workbook.xml", f"{_S}sheet", re.compile(r"xl/worksheets/sheet\d+\.xml")
    )
    for name, part in sheets:
        data = read_part(package, part)
        if data is None:
            continue
        header_pending = True
        previous_row = 0
        formulas: dict[str, str] = {}
        for _, element in ElementTree.iterparse(io.BytesIO(data), events=("end",)):
            if element.tag != f"{_S}row":
                continue
            cells: dict[int, str] = {}
            next_column = 0
            for cell in element.iter(f"{_S}c"):
                column = _column_index(cell.get("r"))
                if column is None:
                    column = next_column
                next_column = column + 1
                value = _cell_value(cell, shared, formulas)
                if value:
                    cells[column] = value
            if cells:
                if header_pending:
                    yield f"{STRUCTURE}# {_normalize(name)}".rstrip()
                    header_pending = False
                number = element.get("r", "")
                row = int(number) if number.isdigit() else previous_row + 1
                if row != previous_row + 1:
                    yield f"{STRUCTURE}row {row}"
                previous_row = row
                yield "\t".join(cells.get(i, "") for i in range(max(cells) + 1))
            element.clear()


def _pptx_lines(package: zipfile.ZipFile) -> Iterator[str]:
    """Yield the paragraphs of a presentation, slide by slide, with speaker notes.

    Each slide with text starts with a mark, so the same paragraphs spread over the slides
    differently give different text. Slides without text are counted in the next mark.
    The notes of a slide follow it, found through the slide's relationships because their
    part names are internal identifiers that do not follow the slide order.
    """
    slides = _ordered_parts(
        package, "ppt/presentation.xml", f"{_P}sldId", re.compile(r"ppt/slides/slide\d+\.xml")
    )
    notes = re.compile(r"ppt/notesSlides/notesSlide\d+\.xml")
    tags = (f"{_A}t", f"{_A}p", {f"{_A}br"})
    names = set(package.namelist())
    seen_notes: set[str] = set()

    def notes_lines(part: str) -> Iterator[str]:
        seen_notes.add(part)
        data = read_part(package, part)
        lines = _paragraphs(data, *tags) if data is not None else []
        if lines:
            yield f"{STRUCTURE}notes"
            yield from lines

    empty_slides = 0
    for _, part in slides:
        data = read_part(package, part)
        lines = _paragraphs(data, *tags) if data is not None else []
        slide_notes = [
            target
            for target in _relationships(package, part).values()
            if notes.fullmatch(target) and target in names and target not in seen_notes
        ]
        following = [line for target in slide_notes for line in notes_lines(target)]
        if not lines and not following:
            empty_slides += 1
            continue
        mark = f"{STRUCTURE}slide"
        yield f"{mark} after {empty_slides} empty" if empty_slides else mark
        empty_slides = 0
        yield from lines
        yield from following

    # Notes that no slide refers to are kept at the end, so no text is lost
    for part in sorted(names, key=_natural_key):
        if notes.fullmatch(part) and part not in seen_notes:
            yield from notes_lines(part)


_EXTRACTORS = {".docx": _docx_lines, ".xlsx": _xlsx_lines, ".pptx": _pptx_lines}


def extract_text(filepath: Path) -> str | None:
    """Extract the text of an Office document, ignoring formatting.

    Args:
        filepath: Path to a .docx, .xlsx or .pptx file

    Returns:
        Normalized text with one line per paragraph or row, or None when the file is not
        a readable Office document or contains no text
    """
    extractor = _EXTRACTORS.get(filepath.suffix.lower())
    if extractor is None:
        return None

    try:
        with zipfile.ZipFile(filepath) as package:
            lines = list(extractor(package))
    except (*PACKAGE_ERRORS, *XML_ERRORS) as e:
        logger.warning(f"Cannot extract text from {filepath}: {e}")
        return None

    return "\n".join(line for line in lines if line) or None
