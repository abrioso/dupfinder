"""Output formatters for duplicate file results."""

import csv
import io
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

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
]


def _role(index: int, filepath: Path, is_reference: ReferenceCheck | None) -> str:
    """Describe what happens to a file of a duplicate group.

    Args:
        index: Position of the file in its group
        filepath: Path to the file
        is_reference: Callable telling whether a file is in a reference directory

    Returns:
        'reference', 'keep' or 'duplicate'
    """
    if is_reference is not None and is_reference(filepath):
        return "reference"
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
    index: int, filepath: Path, is_reference: ReferenceCheck | None
) -> dict[str, Any]:
    """Collect what is reported about one file of a group.

    Args:
        index: Position of the file in its group
        filepath: Path to the file
        is_reference: Callable telling whether a file is in a reference directory

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
        "role": _role(index, filepath, is_reference),
        "size": size,
        "modified": modified,
        "document_modified": properties.modified,
        "document_last_modified_by": properties.last_modified_by,
    }


def _table_line(details: dict[str, Any]) -> str:
    """Format one file of a group for the table output.

    Args:
        details: File details from _file_details

    Returns:
        Line with path, role marker and timestamps
    """
    marker = "" if details["role"] == "duplicate" else f" [{details['role']}]"
    line = f"  - {details['path']}{marker}"
    if details["modified"]:
        line += f"\n      modified: {details['modified']}"
    if details["document_modified"]:
        line += f" | document saved: {details['document_modified']}"
        if details["document_last_modified_by"]:
            line += f" by {details['document_last_modified_by']}"
    return line


def format_json(
    duplicates: dict[str, list[Path]], is_reference: ReferenceCheck | None = None
) -> str:
    """Format duplicates as JSON.

    Args:
        duplicates: Dictionary mapping hash to list of duplicate paths
        is_reference: Callable telling whether a file is in a reference directory

    Returns:
        JSON string
    """
    result = []
    for hash_val, file_list in duplicates.items():
        result.append(
            {
                "hash": hash_val,
                "count": len(file_list),
                "files": [str(f) for f in file_list],
                "details": [_file_details(i, f, is_reference) for i, f in enumerate(file_list)],
            }
        )

    return json.dumps(result, indent=2)


def format_csv(
    duplicates: dict[str, list[Path]], is_reference: ReferenceCheck | None = None
) -> str:
    """Format duplicates as CSV.

    Args:
        duplicates: Dictionary mapping hash to list of duplicate paths
        is_reference: Callable telling whether a file is in a reference directory

    Returns:
        CSV string
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(CSV_COLUMNS)

    # Write data
    for hash_val, file_list in duplicates.items():
        group_size = len(file_list)
        for i, filepath in enumerate(file_list):
            details = _file_details(i, filepath, is_reference)
            writer.writerow(
                [
                    hash_val,
                    details["path"],
                    group_size,
                    details["role"],
                    details["size"],
                    details["modified"],
                    details["document_modified"],
                    details["document_last_modified_by"],
                ]
            )

    return output.getvalue()


def format_table(
    duplicates: dict[str, list[Path]], is_reference: ReferenceCheck | None = None
) -> str:
    """Format duplicates as human-readable table.

    Args:
        duplicates: Dictionary mapping hash to list of duplicate paths
        is_reference: Callable telling whether a file is in a reference directory

    Returns:
        Formatted table string
    """
    if not duplicates:
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

    # Add summary
    lines.append("\n" + "=" * 80)
    lines.append("Summary:")
    lines.append(f"  Duplicate groups: {len(duplicates)}")
    lines.append(f"  Total duplicate files: {total_duplicates}")
    lines.append(f"  Total wasted space: {_format_size(total_wasted_space)}")

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
) -> str:
    """Format duplicate results in the specified format.

    Args:
        duplicates: Dictionary mapping hash to list of duplicate paths
        format_type: Output format ('json', 'csv', or 'table')
        is_reference: Callable telling whether a file is in a reference directory

    Returns:
        Formatted output string
    """
    if format_type == "json":
        return format_json(duplicates, is_reference)
    elif format_type == "csv":
        return format_csv(duplicates, is_reference)
    elif format_type == "table":
        return format_table(duplicates, is_reference)
    else:
        raise ValueError(f"Unknown format type: {format_type}")
