"""Tests for dupfinder formatters module."""

import pytest

from dupfinder.formatters import format_csv, format_json, format_output, format_table


class TestFormatters:
    """Test cases for output formatters."""

    def test_format_json_empty(self):
        """Test JSON formatting with no duplicates."""
        result = format_json({})
        assert result == "[]"

    def test_format_json_with_duplicates(self, tmp_path):
        """Test JSON formatting with duplicates."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"

        duplicates = {"abc123": [file1, file2]}

        result = format_json(duplicates)

        # Parse JSON to verify
        import json

        data = json.loads(result)

        assert len(data) == 1
        assert data[0]["hash"] == "abc123"
        assert data[0]["count"] == 2
        assert len(data[0]["files"]) == 2

    def test_format_csv_empty(self):
        """Test CSV formatting with no duplicates."""
        result = format_csv({})
        # Should only have header
        lines = result.strip().split("\n")
        assert len(lines) == 1
        assert lines[0] == "hash,file_path,group_size"

    def test_format_csv_with_duplicates(self, tmp_path):
        """Test CSV formatting with duplicates."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"

        duplicates = {"abc123": [file1, file2]}

        result = format_csv(duplicates)
        lines = result.strip().split("\n")

        assert len(lines) == 3  # header + 2 files
        assert "hash,file_path,group_size" in lines[0]
        assert "abc123" in lines[1]
        assert "abc123" in lines[2]

    def test_format_table_empty(self):
        """Test table formatting with no duplicates."""
        result = format_table({})
        assert "No duplicates found" in result

    def test_format_table_with_duplicates(self, tmp_path):
        """Test table formatting with duplicates."""
        # Create actual files so we can get stats
        file1 = tmp_path / "file1.txt"
        file1.write_text("content")
        file2 = tmp_path / "file2.txt"
        file2.write_text("content")

        duplicates = {"abc123": [file1, file2]}

        result = format_table(duplicates)

        assert "Duplicate group 1" in result
        assert "abc123" in result
        assert str(file1) in result
        assert str(file2) in result
        assert "Summary:" in result

    def test_format_output_json(self, tmp_path):
        """Test format_output with json format."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"

        duplicates = {"abc123": [file1, file2]}

        result = format_output(duplicates, "json")
        assert "abc123" in result
        # Should be valid JSON
        import json

        json.loads(result)

    def test_format_output_csv(self, tmp_path):
        """Test format_output with csv format."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"

        duplicates = {"abc123": [file1, file2]}

        result = format_output(duplicates, "csv")
        assert "abc123" in result
        assert "hash,file_path,group_size" in result

    def test_format_output_table(self, tmp_path):
        """Test format_output with table format."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("test")
        file2 = tmp_path / "file2.txt"
        file2.write_text("test")

        duplicates = {"abc123": [file1, file2]}

        result = format_output(duplicates, "table")
        assert "Duplicate group" in result
        assert "abc123" in result

    def test_format_output_invalid_format(self):
        """Test format_output with invalid format."""
        with pytest.raises(ValueError):
            format_output({}, "invalid")
