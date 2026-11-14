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

from dupfinder.office import read_part

logger = logging.getLogger(__name__)

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

_WHITESPACE = re.compile(r"\s+")
_NUMBER = re.compile(r"(\d+)")


def _natural_key(name: str) -> list[int | str]:
    """Sort key ordering 'slide2' before 'slide10'."""
    return [int(piece) if piece.isdigit() else piece for piece in _NUMBER.split(name)]


def _normalize(line: str) -> str:
    """Normalize Unicode form and whitespace of a line of text."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", line)).strip()


def _paragraphs(data: bytes, text_tag: str, paragraph_tag: str, break_tags: set[str]) -> list[str]:
    """Extract one line per paragraph from a WordprocessingML or DrawingML part.

    Args:
        data: XML content of the part
        text_tag: Qualified tag of text runs
        paragraph_tag: Qualified tag of paragraphs
        break_tags: Qualified tags rendered as a space (tabs, line breaks)

    Returns:
        Text of each paragraph, in document order
    """
    lines: list[str] = []
    buffer: list[str] = []
    for _, element in ElementTree.iterparse(io.BytesIO(data), events=("end",)):
        tag = element.tag
        if tag == text_tag:
            buffer.append(element.text or "")
        elif tag in break_tags:
            buffer.append(" ")
        elif tag == paragraph_tag:
            lines.append("".join(buffer))
            buffer.clear()
            element.clear()
    if buffer:
        lines.append("".join(buffer))
    return lines


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


def _docx_lines(package: zipfile.ZipFile) -> Iterator[str]:
    """Yield the paragraphs of a Word document, including notes, headers and footers."""
    names = sorted(package.namelist(), key=_natural_key)
    extra = re.compile(r"word/(footnotes|endnotes|header\d*|footer\d*)\.xml")
    for part in ["word/document.xml", *[n for n in names if extra.fullmatch(n)]]:
        data = read_part(package, part)
        if data is not None:
            yield from _paragraphs(data, f"{_W}t", f"{_W}p", {f"{_W}tab", f"{_W}br", f"{_W}cr"})


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
        Text of the cell
    """
    formula = cell.find(f"{_S}f")
    if formula is not None:
        group = formula.get("si") if formula.get("t") == "shared" else None
        if formula.text:
            if group is not None:
                formulas[group] = formula.text
            return "=" + formula.text
        # Follower of a shared formula: refer to the master's text, because the group
        # identifier is an arbitrary number that differs between saves
        return f"=shared({formulas.get(group or '', '')})"
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(f"{_S}t"))
    value = cell.find(f"{_S}v")
    if value is None or value.text is None:
        return ""
    if cell_type == "s":
        try:
            return shared[int(value.text)]
        except (ValueError, IndexError):
            return ""
    if cell_type == "b":
        # Booleans are stored as 1/0 but are not the numbers 1 and 0
        return "TRUE" if value.text.strip() == "1" else "FALSE"
    return value.text


def _xlsx_lines(package: zipfile.ZipFile) -> Iterator[str]:
    """Yield the non-empty rows of a workbook, each sheet preceded by its name.

    Sheet names are only emitted for sheets with content, so a workbook of empty sheets
    yields nothing.
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
        formulas: dict[str, str] = {}
        for _, element in ElementTree.iterparse(io.BytesIO(data), events=("end",)):
            if element.tag == f"{_S}row":
                values = [_cell_value(cell, shared, formulas) for cell in element.iter(f"{_S}c")]
                line = _normalize(" ".join(v for v in values if v))
                if line:
                    if header_pending:
                        yield f"# {name}"
                        header_pending = False
                    yield line
                element.clear()


def _pptx_lines(package: zipfile.ZipFile) -> Iterator[str]:
    """Yield the paragraphs of a presentation: slides in order, then speaker notes."""
    slides = _ordered_parts(
        package, "ppt/presentation.xml", f"{_P}sldId", re.compile(r"ppt/slides/slide\d+\.xml")
    )
    notes = re.compile(r"ppt/notesSlides/notesSlide\d+\.xml")
    parts = [part for _, part in slides]
    parts += [n for n in sorted(package.namelist(), key=_natural_key) if notes.fullmatch(n)]
    for part in parts:
        data = read_part(package, part)
        if data is not None:
            yield from _paragraphs(data, f"{_A}t", f"{_A}p", {f"{_A}br"})


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
            lines = [_normalize(line) for line in extractor(package)]
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError, RuntimeError, KeyError) as e:
        logger.warning(f"Cannot extract text from {filepath}: {e}")
        return None

    return "\n".join(line for line in lines if line) or None
