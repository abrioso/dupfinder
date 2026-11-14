"""Output formatters for duplicate file results."""

import csv
import io
import json
from collections.abc import Callable
from pathlib import Path

ReferenceCheck = Callable[[Path], bool]


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
                "details": [
                    {"path": str(f), "role": _role(i, f, is_reference)}
                    for i, f in enumerate(file_list)
                ],
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
    writer.writerow(["hash", "file_path", "group_size", "role"])

    # Write data
    for hash_val, file_list in duplicates.items():
        group_size = len(file_list)
        for i, filepath in enumerate(file_list):
            writer.writerow([hash_val, str(filepath), group_size, _role(i, filepath, is_reference)])

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
            role = _role(index, filepath, is_reference)
            marker = "" if role == "duplicate" else f" [{role}]"
            lines.append(f"  - {filepath}{marker}")

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
