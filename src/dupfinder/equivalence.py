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

from dupfinder.office import is_office_file

logger = logging.getLogger(__name__)

LEVEL_PACKAGE = 1

# Label requested for reports; the level number is filled in per group
EQUIVALENT_LABEL = "ficheiro equivalente - nível {level} (validar)"

LEGACY_EXTENSIONS = frozenset({".doc", ".xls", ".ppt"})

# Parts that hold metadata or packaging plumbing rather than document content
_IGNORED_PART_PREFIXES = ("docProps/",)
_IGNORED_PARTS = frozenset({"[Content_Types].xml", "_rels/.rels"})

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


def package_signature(filepath: Path) -> str | None:
    """Compute a signature of the content parts of an Office package.

    The signature is built from the name, CRC and size of every part recorded in the ZIP
    directory, so nothing is decompressed. Document properties and packaging plumbing are
    left out, so files that differ only in metadata or compression share a signature.

    Args:
        filepath: Path to the document

    Returns:
        Hex signature, or None if the file is not a readable package
    """
    try:
        with zipfile.ZipFile(filepath) as package:
            entries = sorted(
                (info.filename, info.CRC, info.file_size)
                for info in package.infolist()
                if not info.is_dir()
                and info.filename not in _IGNORED_PARTS
                and not info.filename.startswith(_IGNORED_PART_PREFIXES)
            )
    except (OSError, zipfile.BadZipFile) as e:
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
