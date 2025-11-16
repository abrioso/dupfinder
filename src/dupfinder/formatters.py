"""Output formatters for duplicate file results."""

import csv
import io
import json
from pathlib import Path


def format_json(duplicates: dict[str, list[Path]]) -> str:
    """Format duplicates as JSON.

    Args:
        duplicates: Dictionary mapping hash to list of duplicate paths

    Returns:
        JSON string
    """
    result = []
    for hash_val, file_list in duplicates.items():
        result.append(
            {"hash": hash_val, "count": len(file_list), "files": [str(f) for f in file_list]}
        )

    return json.dumps(result, indent=2)


def format_csv(duplicates: dict[str, list[Path]]) -> str:
    """Format duplicates as CSV.

    Args:
        duplicates: Dictionary mapping hash to list of duplicate paths

    Returns:
        CSV string
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Write header
    writer.writerow(["hash", "file_path", "group_size"])

    # Write data
    for hash_val, file_list in duplicates.items():
        group_size = len(file_list)
        for filepath in file_list:
            writer.writerow([hash_val, str(filepath), group_size])

    return output.getvalue()


def format_table(duplicates: dict[str, list[Path]]) -> str:
    """Format duplicates as human-readable table.

    Args:
        duplicates: Dictionary mapping hash to list of duplicate paths

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

        for filepath in file_list:
            lines.append(f"  - {filepath}")

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


def format_output(duplicates: dict[str, list[Path]], format_type: str = "table") -> str:
    """Format duplicate results in the specified format.

    Args:
        duplicates: Dictionary mapping hash to list of duplicate paths
        format_type: Output format ('json', 'csv', or 'table')

    Returns:
        Formatted output string
    """
    if format_type == "json":
        return format_json(duplicates)
    elif format_type == "csv":
        return format_csv(duplicates)
    elif format_type == "table":
        return format_table(duplicates)
    else:
        raise ValueError(f"Unknown format type: {format_type}")
