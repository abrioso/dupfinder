"""Detection of equivalent Office documents.

Equivalent files are not byte-identical, so they are never candidates for deletion or
hardlinking. They are reported with a label asking for manual validation.
"""

import hashlib
import logging
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from dupfinder.office import (
    MAX_METADATA_SIZE,
    PACKAGE_ERRORS,
    XML_ERRORS,
    is_office_file,
    read_part,
)

logger = logging.getLogger(__name__)

LEVEL_PACKAGE = 1

# Label requested for reports; the level number is filled in per group
EQUIVALENT_LABEL = "ficheiro equivalente - nível {level} (validar)"

LEGACY_EXTENSIONS = frozenset({".doc", ".xls", ".ppt"})

# Relationship types (by their ending) that declare a part as document properties
_METADATA_RELATIONSHIP_TYPES = (
    "/core-properties",
    "/extended-properties",
    "/custom-properties",
    "/thumbnail",
)
_METADATA_FALLBACK_PREFIX = "docProps/"
_RELATIONSHIPS_PART = "_rels/.rels"
# Package descriptors: they say which part is the document and how parts are interpreted,
# so they are compared after dropping their entries about the metadata parts
_DESCRIPTOR_PARTS = frozenset({"[Content_Types].xml", _RELATIONSHIPS_PART})

GroupOrder = Callable[[list[Path]], list[Path]]


@dataclass
class EquivalentGroup:
    """A group of Office documents considered equivalent at some level.

    Attributes:
        level: Equivalence level (1 = same package content)
        key: Value shared by the group (signature or hash)
        files: Files of the group
        similarity: Similarity of each file to the first one, when it is measured
    """

    level: int
    key: str
    files: list[Path]
    similarity: dict[Path, float] = field(default_factory=dict)

    @property
    def label(self) -> str:
        """Label shown in reports for the files of this group."""
        return EQUIVALENT_LABEL.format(level=self.level)


def _parse_part(package: zipfile.ZipFile, name: str) -> ElementTree.Element | None:
    """Parse a small XML part, returning None if it is missing or malformed."""
    data = read_part(package, name, MAX_METADATA_SIZE)
    if data is None:
        return None
    try:
        return ElementTree.fromstring(data)
    except XML_ERRORS:
        return None


def _metadata_parts(package: zipfile.ZipFile) -> set[str]:
    """Find the parts that hold document properties rather than content.

    A part is metadata when the package relationships declare it as such (core, extended
    or custom properties, or the thumbnail). Its location alone does not decide it, so a
    document part that happens to live under docProps/ still counts as content. Packages
    without readable relationships fall back to treating everything under docProps/ as
    metadata.

    Args:
        package: Open Office document

    Returns:
        Names of the metadata parts
    """
    root = _parse_part(package, _RELATIONSHIPS_PART)
    if root is None:
        return {n for n in package.namelist() if n.startswith(_METADATA_FALLBACK_PREFIX)}
    return {
        element.get("Target", "").lstrip("/")
        for element in root
        if element.get("Type", "").endswith(_METADATA_RELATIONSHIP_TYPES)
    }


def _descriptor_entries(
    package: zipfile.ZipFile, name: str, metadata: set[str]
) -> list[str] | None:
    """Summarize a package descriptor without its entries about metadata parts.

    Args:
        package: Open Office document
        name: '[Content_Types].xml' or '_rels/.rels'
        metadata: Names of the metadata parts

    Returns:
        Sorted description of the remaining entries, or None if the part cannot be parsed
    """
    root = _parse_part(package, name)
    if root is None:
        return None

    entries = []
    for element in root:
        # Relationship ids are arbitrary labels and may be renumbered between saves
        attributes = {k: v for k, v in element.attrib.items() if k != "Id"}
        location = attributes.get("PartName") or attributes.get("Target") or ""
        if location.lstrip("/") in metadata:
            continue
        tag = element.tag.rpartition("}")[2]
        entries.append(f"{tag} {sorted(attributes.items())}")
    return sorted(entries)


def package_signature(filepath: Path) -> str | None:
    """Compute a signature of the content parts of an Office package.

    The signature is built from the name, CRC and size of every part recorded in the ZIP
    directory, so document content is not decompressed. Document properties are left out,
    and the two small package descriptors are compared without their entries about those
    properties, so files that differ only in metadata or compression share a signature.

    Args:
        filepath: Path to the document

    Returns:
        Hex signature, or None if the file is not a readable package
    """
    try:
        with zipfile.ZipFile(filepath) as package:
            metadata = _metadata_parts(package)
            entries = sorted(
                (info.filename, info.CRC, info.file_size)
                for info in package.infolist()
                if not info.is_dir()
                and info.filename not in _DESCRIPTOR_PARTS
                and info.filename not in metadata
            )
            descriptors = []
            for name in sorted(_DESCRIPTOR_PARTS & set(package.namelist())):
                summary = _descriptor_entries(package, name, metadata)
                if summary is None:
                    # Unparseable descriptor: fall back to comparing it byte for byte
                    info = package.getinfo(name)
                    summary = [f"raw {info.CRC} {info.file_size}"]
                descriptors.append((name, summary))
    except PACKAGE_ERRORS as e:
        logger.warning(
            f"Skipping {filepath}: not a readable Office package "
            f"(password-protected or corrupt?): {e}"
        )
        return None

    if not entries:
        return None

    hasher = hashlib.blake2b(digest_size=16)
    for name, crc, size in entries:
        hasher.update(f"{name}\0{crc}\0{size}\n".encode())
    for name, summary in descriptors:
        hasher.update(f"{name}\0{summary}\n".encode())
    return hasher.hexdigest()


class EquivalenceFinder:
    """Find equivalent Office documents among scanned files."""

    def __init__(
        self,
        levels: Iterable[int],
        order_group: GroupOrder | None = None,
        num_threads: int = 4,
    ):
        """Initialize the equivalence finder.

        Args:
            levels: Equivalence levels to search for
            order_group: Callable ordering the files of a group (file to prefer first)
            num_threads: Number of threads for parallel processing
        """
        self.levels = set(levels)
        self.order_group: GroupOrder = order_group or (lambda files: sorted(files, key=str))
        self.num_threads = num_threads

    def find(
        self, files: list[Path], duplicates: dict[str, list[Path]] | None = None
    ) -> list[EquivalentGroup]:
        """Find groups of equivalent documents.

        Exact duplicates are represented by the first file of their group, so a pair is
        only ever reported once, at the lowest level where it matches.

        Args:
            files: Scanned files
            duplicates: Exact duplicate groups already found

        Returns:
            Equivalent groups, ordered by level
        """
        if not self.levels:
            return []

        legacy = sum(1 for f in files if f.suffix.lower() in LEGACY_EXTENSIONS)
        if legacy:
            logger.info(
                f"{legacy} legacy Office files (.doc, .xls, .ppt) are not checked for equivalence"
            )

        redundant = {f for group in (duplicates or {}).values() for f in group[1:]}
        candidates = sorted((f for f in files if is_office_file(f) and f not in redundant), key=str)
        logger.info(f"Checking {len(candidates)} Office documents for equivalence")

        groups: list[EquivalentGroup] = []

        with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            signatures = dict(zip(candidates, executor.map(package_signature, candidates)))
        # Unreadable packages cannot be compared at any level
        candidates = [f for f in candidates if signatures[f] is not None]

        if LEVEL_PACKAGE in self.levels:
            found = self._group_by_key(candidates, signatures, LEVEL_PACKAGE)
            groups.extend(found)
            candidates = self._representatives(candidates, found)

        logger.info(f"Found {len(groups)} groups of equivalent documents")
        return groups

    def _group_by_key(
        self, candidates: list[Path], keys: dict[Path, str | None], level: int
    ) -> list[EquivalentGroup]:
        """Group documents of the same type that share a key.

        Args:
            candidates: Documents to group
            keys: Key of each document (documents without key are left out)
            level: Equivalence level of the resulting groups

        Returns:
            Groups with at least two files
        """
        buckets: dict[tuple[str, str], list[Path]] = defaultdict(list)
        for filepath in candidates:
            key = keys.get(filepath)
            if key is not None:
                buckets[(filepath.suffix.lower(), key)].append(filepath)

        groups = [
            EquivalentGroup(level=level, key=key, files=self.order_group(members))
            for (_, key), members in buckets.items()
            if len(members) > 1
        ]
        return sorted(groups, key=lambda g: str(g.files[0]))

    @staticmethod
    def _representatives(candidates: list[Path], groups: list[EquivalentGroup]) -> list[Path]:
        """Keep one file per group for the comparison at the next level.

        Args:
            candidates: Documents compared at the current level
            groups: Groups found at the current level

        Returns:
            Candidates without the non-first files of each group
        """
        redundant = {f for group in groups for f in group.files[1:]}
        return [f for f in candidates if f not in redundant]
