"""Output formatters for duplicate and equivalent file results."""

import csv
import io
import json
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from dupfinder.equivalence import EquivalentGroup
from dupfinder.office import read_core_properties

ReferenceCheck = Callable[[Path], bool]

CSV_COLUMNS = [
    "hash",
    "file_path",
    "group_size",
    "role",
    "size",
    "modified",
    "document_modified",
    "document_last_modified_by",
    "match_type",
    "level",
    "label",
    "similarity",
]

MATCH_EXACT = "exact"
MATCH_EQUIVALENT = "equivalent"


def _role(
    index: int,
    filepath: Path,
    is_reference: ReferenceCheck | None,
    match_type: str = MATCH_EXACT,
) -> str:
    """Describe the role of a file within its group.

    Args:
        index: Position of the file in its group
        filepath: Path to the file
        is_reference: Callable telling whether a file is in a reference directory
        match_type: 'exact' for duplicates or 'equivalent' for equivalent documents

    Returns:
        'reference', 'keep', 'duplicate' or 'equivalent'
    """
    if is_reference is not None and is_reference(filepath):
        return "reference"
    if match_type == MATCH_EQUIVALENT:
        return "equivalent"
    return "keep" if index == 0 else "duplicate"


def _format_timestamp(timestamp: float) -> str:
    """Format a file system timestamp as ISO 8601 local time with UTC offset.

    Args:
        timestamp: Seconds since the epoch

    Returns:
        Timestamp such as '2026-11-12T08:38:00+00:00'
    """
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def _file_details(
    index: int,
    filepath: Path,
    is_reference: ReferenceCheck | None,
    match_type: str = MATCH_EXACT,
) -> dict[str, Any]:
    """Collect what is reported about one file of a group.

    Args:
        index: Position of the file in its group
        filepath: Path to the file
        is_reference: Callable telling whether a file is in a reference directory
        match_type: 'exact' for duplicates or 'equivalent' for equivalent documents

    Returns:
        Dictionary with path, role, size, file system modification time and, for Office
        documents, the save time and last author recorded inside the document
    """
    try:
        stat = filepath.stat()
        size: int | None = stat.st_size
        modified: str | None = _format_timestamp(stat.st_mtime)
    except OSError:
        size = None
        modified = None

    properties = read_core_properties(filepath)
    return {
        "path": str(filepath),
        "role": _role(index, filepath, is_reference, match_type),
        "size": size,
        "modified": modified,
        "document_modified": properties.modified,
        "document_last_modified_by": properties.last_modified_by,
    }


def _equivalent_details(
    group: EquivalentGroup, is_reference: ReferenceCheck | None
) -> list[dict[str, Any]]:
    """Collect the details of every file of an equivalent group.

    Args:
        group: Equivalent group
        is_reference: Callable telling whether a file is in a reference directory

    Returns:
        File details, with the similarity to the first file when it was measured
    """
    result = []
    for index, filepath in enumerate(group.files):
        details = _file_details(index, filepath, is_reference, MATCH_EQUIVALENT)
        if group.similarity:
            details["similarity"] = group.similarity.get(filepath)
        result.append(details)
    return result


def _table_line(details: dict[str, Any]) -> str:
    """Format one file of a group for the table output.

    Args:
        details: File details from _file_details

    Returns:
        Line with path, role marker and timestamps
    """
    marker = f" [{details['role']}]" if details["role"] in ("keep", "reference") else ""
    line = f"  - {details['path']}{marker}"
    if details.get("similarity") is not None:
        line += f" (similarity {details['similarity']:.2f})"
    if details["modified"]:
        line += f"\n      modified: {details['modified']}"
    if details["document_modified"] or details["document_last_modified_by"]:
        line += "\n      document saved:" if not details["modified"] else " | document saved:"
        if details["document_modified"]:
            line += f" {details['document_modified']}"
        if details["document_last_modified_by"]:
            line += f" by {details['document_last_modified_by']}"
    return line


def format_json(
    duplicates: dict[str, list[Path]],
    is_reference: ReferenceCheck | None = None,
    equivalents: Sequence[EquivalentGroup] = (),
) -> str:
    """Format results as JSON.

    Args:
        duplicates: Dictionary mapping hash to list of duplicate paths
        is_reference: Callable telling whether a file is in a reference directory
        equivalents: Groups of equivalent documents

    Returns:
        JSON string
    """
    result: list[dict[str, Any]] = []
    for hash_val, file_list in duplicates.items():
        result.append(
            {
                "hash": hash_val,
                "count": len(file_list),
                "files": [str(f) for f in file_list],
                "match_type": MATCH_EXACT,
                "details": [_file_details(i, f, is_reference) for i, f in enumerate(file_list)],
            }
        )

    for group in equivalents:
        result.append(
            {
                "hash": group.key,
                "count": len(group.files),
                "files": [str(f) for f in group.files],
                "match_type": MATCH_EQUIVALENT,
                "level": group.level,
                "label": group.label,
                "details": _equivalent_details(group, is_reference),
            }
        )

    return json.dumps(result, indent=2, ensure_ascii=False)


def format_csv(
    duplicates: dict[str, list[Path]],
    is_reference: ReferenceCheck | None = None,
    equivalents: Sequence[EquivalentGroup] = (),
) -> str:
    """Format results as CSV.

    Args:
        duplicates: Dictionary mapping hash to list of duplicate paths
        is_reference: Callable telling whether a file is in a reference directory
        equivalents: Groups of equivalent documents

    Returns:
        CSV string
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_COLUMNS)

    def write_row(key: str, group_size: int, details: dict[str, Any], *extra: Any) -> None:
        writer.writerow(
            [
                key,
                details["path"],
                group_size,
                details["role"],
                details["size"],
                details["modified"],
                details["document_modified"],
                details["document_last_modified_by"],
                *extra,
            ]
        )

    for hash_val, file_list in duplicates.items():
        for i, filepath in enumerate(file_list):
            details = _file_details(i, filepath, is_reference)
            write_row(hash_val, len(file_list), details, MATCH_EXACT, "", "", "")

    for group in equivalents:
        for details in _equivalent_details(group, is_reference):
            similarity = details.get("similarity")
            write_row(
                group.key,
                len(group.files),
                details,
                MATCH_EQUIVALENT,
                group.level,
                group.label,
                "" if similarity is None else f"{similarity:.2f}",
            )

    return output.getvalue()


def format_table(
    duplicates: dict[str, list[Path]],
    is_reference: ReferenceCheck | None = None,
    equivalents: Sequence[EquivalentGroup] = (),
) -> str:
    """Format results as human-readable table.

    Args:
        duplicates: Dictionary mapping hash to list of duplicate paths
        is_reference: Callable telling whether a file is in a reference directory
        equivalents: Groups of equivalent documents

    Returns:
        Formatted table string
    """
    if not duplicates and not equivalents:
        return "No duplicates found."

    lines = []
    total_duplicates = 0
    total_wasted_space = 0

    for i, (hash_val, file_list) in enumerate(duplicates.items(), 1):
        # Get file size
        try:
            file_size = file_list[0].stat().st_size
        except OSError:
            file_size = 0

        wasted_space = file_size * (len(file_list) - 1)
        total_wasted_space += wasted_space
        total_duplicates += len(file_list) - 1

        lines.append(
            f"\nDuplicate group {i} ({len(file_list)} files, {_format_size(file_size)} each):"
        )
        lines.append(f"Hash: {hash_val}")
        lines.append(f"Wasted space: {_format_size(wasted_space)}")

        for index, filepath in enumerate(file_list):
            lines.append(_table_line(_file_details(index, filepath, is_reference)))

    for i, group in enumerate(equivalents, 1):
        lines.append(f"\nEquivalent group {i} ({len(group.files)} files): {group.label}")
        lines.append(f"Key: {group.key}")
        for details in _equivalent_details(group, is_reference):
            lines.append(_table_line(details))

    # Add summary
    lines.append("\n" + "=" * 80)
    lines.append("Summary:")
    lines.append(f"  Duplicate groups: {len(duplicates)}")
    lines.append(f"  Total duplicate files: {total_duplicates}")
    lines.append(f"  Total wasted space: {_format_size(total_wasted_space)}")
    if equivalents:
        lines.append(f"  Equivalent groups (to validate, never deleted): {len(equivalents)}")

    return "\n".join(lines)


def _format_size(size: int) -> str:
    """Format file size in human-readable format.

    Args:
        size: Size in bytes

    Returns:
        Formatted size string
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def format_output(
    duplicates: dict[str, list[Path]],
    format_type: str = "table",
    is_reference: ReferenceCheck | None = None,
    equivalents: Sequence[EquivalentGroup] = (),
) -> str:
    """Format results in the specified format.

    Args:
        duplicates: Dictionary mapping hash to list of duplicate paths
        format_type: Output format ('json', 'csv', or 'table')
        is_reference: Callable telling whether a file is in a reference directory
        equivalents: Groups of equivalent documents

    Returns:
        Formatted output string
    """
    if format_type == "json":
        return format_json(duplicates, is_reference, equivalents)
    elif format_type == "csv":
        return format_csv(duplicates, is_reference, equivalents)
    elif format_type == "table":
        return format_table(duplicates, is_reference, equivalents)
    else:
        raise ValueError(f"Unknown format type: {format_type}")
