"""Tests for dupfinder CLI module."""

import sys

from dupfinder.cli import main, parse_args


class TestCLI:
    """Test cases for CLI interface."""

    def test_parse_args_basic(self, tmp_path):
        """Test basic argument parsing."""
        args = parse_args([str(tmp_path)])

        assert args.paths == [tmp_path]
        assert args.hash_algo == "xxhash"
        assert args.output == "table"
        assert args.threads == 4

    def test_parse_args_hash_algo(self, tmp_path):
        """Test hash algorithm argument."""
        args = parse_args([str(tmp_path), "--hash-algo", "blake2"])
        assert args.hash_algo == "blake2"

    def test_parse_args_output_format(self, tmp_path):
        """Test output format argument."""
        args = parse_args([str(tmp_path), "--output", "json"])
        assert args.output == "json"

    def test_parse_args_size_filters(self, tmp_path):
        """Test size filter arguments."""
        args = parse_args([str(tmp_path), "--min-size", "100", "--max-size", "1000"])
        assert args.min_size == 100
        assert args.max_size == 1000

    def test_parse_args_exclude_patterns(self, tmp_path):
        """Test exclude patterns argument."""
        args = parse_args([str(tmp_path), "--exclude", "*.log", "--exclude", "*.tmp"])
        assert args.exclude == ["*.log", "*.tmp"]

    def test_parse_args_flags(self, tmp_path):
        """Test boolean flag arguments."""
        args = parse_args(
            [str(tmp_path), "--respect-gitignore", "--follow-symlinks", "--dry-run", "--verbose"]
        )
        assert args.respect_gitignore is True
        assert args.follow_symlinks is True
        assert args.dry_run is True
        assert args.verbose is True

    def test_parse_args_delete(self, tmp_path):
        """Test delete argument."""
        args = parse_args([str(tmp_path), "--delete", "--dry-run"])
        assert args.delete is True

    def test_parse_args_hardlink(self, tmp_path):
        """Test hardlink argument."""
        args = parse_args([str(tmp_path), "--hardlink", "--dry-run"])
        assert args.hardlink is True

    def test_parse_args_threads(self, tmp_path):
        """Test threads argument."""
        args = parse_args([str(tmp_path), "--threads", "8"])
        assert args.threads == 8

    def test_parse_args_output_file(self, tmp_path):
        """Test output file argument."""
        output_file = tmp_path / "output.json"
        args = parse_args([str(tmp_path), "--output-file", str(output_file)])
        assert args.output_file == output_file

    def test_main_no_duplicates(self, tmp_path):
        """Test main with no duplicates."""
        # Create unique files
        file1 = tmp_path / "file1.txt"
        file1.write_text("content1")
        file2 = tmp_path / "file2.txt"
        file2.write_text("content2")

        # Run main
        sys.argv = ["dupfinder", str(tmp_path)]
        result = main()

        assert result == 0

    def test_main_with_duplicates(self, tmp_path, capsys):
        """Test main with duplicates."""
        # Create duplicate files
        content = "duplicate content"
        file1 = tmp_path / "file1.txt"
        file1.write_text(content)
        file2 = tmp_path / "file2.txt"
        file2.write_text(content)

        # Run main
        sys.argv = ["dupfinder", str(tmp_path)]
        result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Duplicate group" in captured.out

    def test_main_json_output(self, tmp_path, capsys):
        """Test main with JSON output."""
        # Create duplicate files
        content = "duplicate"
        file1 = tmp_path / "file1.txt"
        file1.write_text(content)
        file2 = tmp_path / "file2.txt"
        file2.write_text(content)

        # Run main
        sys.argv = ["dupfinder", str(tmp_path), "--output", "json"]
        result = main()

        assert result == 0
        captured = capsys.readouterr()
        # Should be valid JSON
        import json

        json.loads(captured.out)

    def test_main_output_to_file(self, tmp_path):
        """Test main with output to file."""
        # Create duplicate files
        content = "duplicate"
        file1 = tmp_path / "file1.txt"
        file1.write_text(content)
        file2 = tmp_path / "file2.txt"
        file2.write_text(content)

        output_file = tmp_path / "output.txt"

        # Run main
        sys.argv = ["dupfinder", str(tmp_path), "--output-file", str(output_file)]
        result = main()

        assert result == 0
        assert output_file.exists()
        output_content = output_file.read_text()
        assert "Duplicate group" in output_content

    def test_main_nonexistent_path(self):
        """Test main with nonexistent path."""
        sys.argv = ["dupfinder", "/nonexistent/path"]
        result = main()

        assert result == 1

    def test_main_delete_and_hardlink_conflict(self, tmp_path):
        """Test main with conflicting delete and hardlink options."""
        sys.argv = ["dupfinder", str(tmp_path), "--delete", "--hardlink"]
        result = main()

        assert result == 1
