"""Helpers for Office Open XML documents (.docx, .xlsx, .pptx)."""

import logging
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

# Errors raised while opening or reading a damaged or unsupported package
PACKAGE_ERRORS = (OSError, zipfile.BadZipFile, zlib.error, RuntimeError, EOFError)

OFFICE_EXTENSIONS = frozenset({".docx", ".xlsx", ".pptx"})

# Parts larger than this are not parsed, to bound memory use on malformed packages
MAX_PART_SIZE = 256 * 1024 * 1024

# Properties and package descriptors are tiny; anything larger is malformed or hostile
MAX_METADATA_SIZE = 1024 * 1024

RELATIONSHIPS_PART = "_rels/.rels"
CORE_PROPERTIES_PART = "docProps/core.xml"
_CORE_PROPERTIES_TYPE = "/core-properties"
_NS_CORE = "{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}"
_NS_DCTERMS = "{http://purl.org/dc/terms/}"


@dataclass(frozen=True)
class CoreProperties:
    """Metadata stored inside an Office document.

    Attributes:
        modified: Last save time recorded by the application (W3CDTF string) or None
        last_modified_by: Name of the last author recorded by the application or None
    """

    modified: str | None = None
    last_modified_by: str | None = None


def is_office_file(filepath: Path) -> bool:
    """Check whether a path has a supported Office Open XML extension.

    Args:
        filepath: Path to the file

    Returns:
        True for .docx, .xlsx and .pptx files
    """
    return filepath.suffix.lower() in OFFICE_EXTENSIONS


def read_part(package: zipfile.ZipFile, name: str, max_size: int = MAX_PART_SIZE) -> bytes | None:
    """Read one part of an open package.

    Args:
        package: Open Office document
        name: Part name inside the package
        max_size: Largest uncompressed size accepted

    Returns:
        Part content, or None if the part is missing or too large
    """
    try:
        info = package.getinfo(name)
    except KeyError:
        return None
    if info.file_size > max_size:
        logger.warning(f"Skipping oversized part {name} in {package.filename}")
        return None
    return package.read(info)


def _core_properties_part(package: zipfile.ZipFile) -> str:
    """Find the core properties part declared by the package relationships.

    Args:
        package: Open Office document

    Returns:
        Declared part name, or the conventional 'docProps/core.xml' when none is declared
    """
    data = read_part(package, RELATIONSHIPS_PART, MAX_METADATA_SIZE)
    if data is not None:
        try:
            for relationship in ElementTree.fromstring(data):
                if relationship.get("Type", "").endswith(_CORE_PROPERTIES_TYPE):
                    target = relationship.get("Target", "").lstrip("/")
                    if target:
                        return target
        except ElementTree.ParseError:
            pass
    return CORE_PROPERTIES_PART


def read_core_properties(filepath: Path) -> CoreProperties:
    """Read the save time and last author recorded inside an Office document.

    Unlike the file system timestamp, these survive copies and downloads.

    Args:
        filepath: Path to the document

    Returns:
        Core properties; empty when the file is not a readable Office document
    """
    if not is_office_file(filepath):
        return CoreProperties()

    try:
        with zipfile.ZipFile(filepath) as package:
            data = read_part(package, _core_properties_part(package), MAX_METADATA_SIZE)
        if data is None:
            return CoreProperties()
        root = ElementTree.fromstring(data)
    except (*PACKAGE_ERRORS, ElementTree.ParseError) as e:
        logger.debug(f"Cannot read document properties of {filepath}: {e}")
        return CoreProperties()

    def text_of(tag: str) -> str | None:
        element = root.find(tag)
        if element is None or element.text is None:
            return None
        return element.text.strip() or None

    return CoreProperties(
        modified=text_of(f"{_NS_DCTERMS}modified"),
        last_modified_by=text_of(f"{_NS_CORE}lastModifiedBy"),
    )
