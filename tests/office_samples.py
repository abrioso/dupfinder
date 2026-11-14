"""Builders for minimal Office Open XML files used by the tests."""

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def core_xml(modified: str = "2026-01-02T03:04:05Z", author: str = "Ana") -> str:
    """Build a docProps/core.xml part."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
        'core-properties" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<cp:lastModifiedBy>{escape(author)}</cp:lastModifiedBy>"
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{modified}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def _write_package(
    path: Path, parts: dict[str, str], modified: str, author: str, compression: int
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression) as package:
        for name, content in parts.items():
            package.writestr(name, content)
        package.writestr("docProps/core.xml", core_xml(modified, author))
    return path


def make_docx(
    path: Path,
    paragraphs: list[str],
    *,
    bold: bool = False,
    modified: str = "2026-01-02T03:04:05Z",
    author: str = "Ana",
    compression: int = zipfile.ZIP_DEFLATED,
) -> Path:
    """Write a minimal .docx with one run per paragraph."""
    run_props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    body = "".join(
        f'<w:p><w:r>{run_props}<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
        for text in paragraphs
    )
    document = f'<w:document xmlns:w="{_W}"><w:body>{body}</w:body></w:document>'
    return _write_package(path, {"word/document.xml": document}, modified, author, compression)


def make_xlsx(
    path: Path,
    sheets: dict[str, list[list[object]]],
    *,
    style: int = 0,
    modified: str = "2026-01-02T03:04:05Z",
    author: str = "Ana",
) -> Path:
    """Write a minimal .xlsx.

    Strings go to the shared strings table, numbers are stored inline and strings
    starting with '=' become formulas.
    """
    shared: list[str] = []
    parts: dict[str, str] = {}
    sheet_entries = []
    relationships = []
    for number, (name, rows) in enumerate(sheets.items(), 1):
        xml_rows = []
        for r, row in enumerate(rows, 1):
            cells = []
            for c, value in enumerate(row):
                ref = f"{chr(ord('A') + c)}{r}"
                if value is None:
                    continue
                if isinstance(value, str) and value.startswith("="):
                    cells.append(f'<c r="{ref}" s="{style}"><f>{escape(value[1:])}</f><v>0</v></c>')
                elif isinstance(value, str):
                    if value not in shared:
                        shared.append(value)
                    index = shared.index(value)
                    cells.append(f'<c r="{ref}" s="{style}" t="s"><v>{index}</v></c>')
                else:
                    cells.append(f'<c r="{ref}" s="{style}"><v>{value}</v></c>')
            xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
        parts[f"xl/worksheets/sheet{number}.xml"] = (
            f'<worksheet xmlns="{_S}"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
        )
        sheet_entries.append(
            f'<sheet name="{escape(name)}" sheetId="{number}" r:id="rId{number}"/>'
        )
        relationships.append(
            f'<Relationship Id="rId{number}" Type="{_R}/worksheet" '
            f'Target="worksheets/sheet{number}.xml"/>'
        )
    parts["xl/workbook.xml"] = (
        f'<workbook xmlns="{_S}" xmlns:r="{_R}"><sheets>{"".join(sheet_entries)}</sheets>'
        "</workbook>"
    )
    parts["xl/_rels/workbook.xml.rels"] = (
        f'<Relationships xmlns="{_REL}">{"".join(relationships)}</Relationships>'
    )
    parts["xl/sharedStrings.xml"] = (
        f'<sst xmlns="{_S}">' + "".join(f"<si><t>{escape(t)}</t></si>" for t in shared) + "</sst>"
    )
    return _write_package(path, parts, modified, author, zipfile.ZIP_DEFLATED)


def make_pptx(
    path: Path,
    slides: list[list[str]],
    *,
    size: int = 1800,
    modified: str = "2026-01-02T03:04:05Z",
    author: str = "Ana",
) -> Path:
    """Write a minimal .pptx with one text paragraph per string."""
    parts: dict[str, str] = {}
    slide_ids = []
    relationships = []
    for number, texts in enumerate(slides, 1):
        paragraphs = "".join(
            f'<a:p><a:r><a:rPr sz="{size}"/><a:t>{escape(text)}</a:t></a:r></a:p>' for text in texts
        )
        parts[f"ppt/slides/slide{number}.xml"] = (
            f'<p:sld xmlns:p="{_P}" xmlns:a="{_A}"><p:cSld><p:spTree><p:sp><p:txBody>'
            f"{paragraphs}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
        )
        slide_ids.append(f'<p:sldId id="{255 + number}" r:id="rId{number}"/>')
        relationships.append(
            f'<Relationship Id="rId{number}" Type="{_R}/slide" '
            f'Target="slides/slide{number}.xml"/>'
        )
    parts["ppt/presentation.xml"] = (
        f'<p:presentation xmlns:p="{_P}" xmlns:r="{_R}"><p:sldIdLst>{"".join(slide_ids)}'
        "</p:sldIdLst></p:presentation>"
    )
    parts["ppt/_rels/presentation.xml.rels"] = (
        f'<Relationships xmlns="{_REL}">{"".join(relationships)}</Relationships>'
    )
    return _write_package(path, parts, modified, author, zipfile.ZIP_DEFLATED)
