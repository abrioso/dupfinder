"""Detection of equivalent Office documents.

Equivalent files are not byte-identical, so they are never candidates for deletion or
hardlinking. They are reported with a label asking for manual validation.
"""

import hashlib
import heapq
import logging
import math
import re
import zipfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from dupfinder.office import MAX_METADATA_SIZE, is_office_file, read_part
from dupfinder.office_text import extract_text

try:
    import xxhash

    HAS_XXHASH = True
except ImportError:
    HAS_XXHASH = False

logger = logging.getLogger(__name__)

LEVEL_PACKAGE = 1
LEVEL_TEXT = 2
LEVEL_SIMILAR = 3

DEFAULT_SIMILARITY_THRESHOLD = 0.9

# Similarity is measured on overlapping sequences of words (shingles)
SHINGLE_WORDS = 4
# Each document is summarized by its smallest shingle hashes (bottom-k sketch)
SKETCH_SIZE = 256
# A shingle shared by more documents than this is not expanded into every pair of them;
# only documents adjacent in path order are compared, which bounds the work
MAX_SHARED_DOCUMENTS = 1000

_WORD = re.compile(r"\w+")

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
        level: Equivalence level (1 = same package content, 2 = same text,
            3 = similar text)
        key: Value shared by the group (signature, text hash or group identifier)
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
    except ElementTree.ParseError:
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
    except (OSError, zipfile.BadZipFile, RuntimeError) as e:
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


def _hash_shingle(shingle: str) -> int:
    """Hash a shingle to a 64-bit integer that is stable across runs."""
    data = shingle.encode()
    if HAS_XXHASH:
        return xxhash.xxh64_intdigest(data)
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "big")


def text_hash(text: str) -> str:
    """Hash the extracted text of a document.

    Args:
        text: Normalized text from extract_text

    Returns:
        Hex digest shared by documents with exactly the same text
    """
    return hashlib.blake2b(text.encode(), digest_size=16).hexdigest()


def text_sketch(text: str) -> tuple[int, ...]:
    """Summarize a text by the smallest hashes of its word shingles.

    Args:
        text: Normalized text from extract_text

    Returns:
        Sorted tuple with at most SKETCH_SIZE hashes; empty when the text has no words
    """
    words = _WORD.findall(text.casefold())
    if not words:
        return ()
    count = max(1, len(words) - SHINGLE_WORDS + 1)
    hashes = {_hash_shingle(" ".join(words[i : i + SHINGLE_WORDS])) for i in range(count)}
    return tuple(heapq.nsmallest(SKETCH_SIZE, hashes))


def sketch_similarity(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    """Estimate the Jaccard similarity of two texts from their sketches.

    The result is exact when both texts have at most SKETCH_SIZE distinct shingles.

    Args:
        a: Sketch of the first text
        b: Sketch of the second text

    Returns:
        Similarity between 0.0 and 1.0
    """
    if not a or not b:
        return 0.0
    set_a, set_b = set(a), set(b)
    union = heapq.nsmallest(SKETCH_SIZE, set_a | set_b)
    shared = sum(1 for h in union if h in set_a and h in set_b)
    return shared / len(union)


class EquivalenceFinder:
    """Find equivalent Office documents among scanned files."""

    def __init__(
        self,
        levels: Iterable[int],
        order_group: GroupOrder | None = None,
        num_threads: int = 4,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ):
        """Initialize the equivalence finder.

        Args:
            levels: Equivalence levels to search for
            order_group: Callable ordering the files of a group (file to prefer first)
            num_threads: Number of threads for parallel processing
            similarity_threshold: Minimum similarity (0-1] of a level 3 pair

        Raises:
            ValueError: If the similarity threshold is out of range
        """
        if not 0 < similarity_threshold <= 1:
            raise ValueError("Similarity threshold must be greater than 0 and at most 1")

        self.similarity_threshold = similarity_threshold
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

        if self.levels & {LEVEL_TEXT, LEVEL_SIMILAR}:
            want_sketch = LEVEL_SIMILAR in self.levels

            def fingerprint(filepath: Path) -> tuple[str | None, tuple[int, ...]]:
                text = extract_text(filepath)
                if text is None:
                    return None, ()
                return text_hash(text), text_sketch(text) if want_sketch else ()

            with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
                fingerprints = dict(zip(candidates, executor.map(fingerprint, candidates)))

            if LEVEL_TEXT in self.levels:
                hashes = {f: fingerprints[f][0] for f in candidates}
                found = self._group_by_key(candidates, hashes, LEVEL_TEXT)
                groups.extend(found)
                candidates = self._representatives(candidates, found)

            if LEVEL_SIMILAR in self.levels:
                sketches = {f: fingerprints[f][1] for f in candidates if fingerprints[f][1]}
                groups.extend(self._group_similar(sketches))

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

    def _group_similar(self, sketches: dict[Path, tuple[int, ...]]) -> list[EquivalentGroup]:
        """Group documents of the same type whose text similarity reaches the threshold.

        Documents with identical sketches are merged directly. Candidate pairs for the
        others come from an inverted index of sketch hashes, so documents with nothing in
        common are never compared. Pairs are merged transitively.

        Args:
            sketches: Sketch of each document with text

        Returns:
            Groups with at least two files, with each file's similarity to the first one
        """
        files = sorted(sketches, key=str)
        parent = list(range(len(files)))

        def root(position: int) -> int:
            while parent[position] != position:
                parent[position] = parent[parent[position]]
                position = parent[position]
            return position

        # Documents with the same sketch need no comparison; one of them stands for all
        first_with_sketch: dict[tuple[str, tuple[int, ...]], int] = {}
        index: dict[tuple[str, int], list[int]] = defaultdict(list)
        for position, filepath in enumerate(files):
            suffix = filepath.suffix.lower()
            first = first_with_sketch.setdefault((suffix, sketches[filepath]), position)
            if first != position:
                parent[position] = first
                continue
            for value in sketches[filepath]:
                index[(suffix, value)].append(position)

        shared_counts: Counter[tuple[int, int]] = Counter()
        neighbours: set[tuple[int, int]] = set()
        for positions in index.values():
            if len(positions) > MAX_SHARED_DOCUMENTS:
                neighbours.update(zip(positions, positions[1:]))
            else:
                for i, first in enumerate(positions):
                    for second in positions[i + 1 :]:
                        shared_counts[(first, second)] += 1

        candidates = set(neighbours)
        for (first, second), shared in shared_counts.items():
            sketch_a, sketch_b = sketches[files[first]], sketches[files[second]]
            # The similarity cannot exceed the shared fraction of the larger sketch
            if shared >= math.ceil(self.similarity_threshold * max(len(sketch_a), len(sketch_b))):
                candidates.add((first, second))

        for first, second in sorted(candidates):
            if root(first) == root(second):
                continue
            similarity = sketch_similarity(sketches[files[first]], sketches[files[second]])
            if similarity >= self.similarity_threshold:
                parent[root(first)] = root(second)

        clusters: dict[int, list[Path]] = defaultdict(list)
        for position, filepath in enumerate(files):
            clusters[root(position)].append(filepath)

        ordered = sorted(
            (self.order_group(members) for members in clusters.values() if len(members) > 1),
            key=lambda members: str(members[0]),
        )
        return [
            EquivalentGroup(
                level=LEVEL_SIMILAR,
                key=f"similar-{number:04d}",
                files=members,
                similarity={
                    f: round(sketch_similarity(sketches[members[0]], sketches[f]), 4)
                    for f in members
                },
            )
            for number, members in enumerate(ordered, 1)
        ]

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
