"""Tests for size argument validation in dupfinder CLI."""

import sys

from dupfinder.cli import main, parse_args


class TestSizeValidation:
    """Test cases for --min-size and --max-size validation."""

    def test_negative_min_size(self, tmp_path, capsys, caplog):
        """Test that negative --min-size is rejected."""
        # Create a test directory
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Try to run with negative min-size
        sys.argv = ["dupfinder", str(test_dir), "--min-size", "-1"]
        result = main()

        # Should fail with exit code 1
        assert result == 1

        # Should log an error message
        assert "--min-size must be non-negative" in caplog.text

    def test_negative_max_size(self, tmp_path, capsys, caplog):
        """Test that negative --max-size is rejected."""
        # Create a test directory
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Try to run with negative max-size
        sys.argv = ["dupfinder", str(test_dir), "--max-size", "-1"]
        result = main()

        # Should fail with exit code 1
        assert result == 1

        # Should log an error message
        assert "--max-size must be non-negative" in caplog.text

    def test_min_size_greater_than_max_size(self, tmp_path, capsys, caplog):
        """Test that min-size > max-size is rejected."""
        # Create a test directory
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Try to run with min-size > max-size
        sys.argv = ["dupfinder", str(test_dir), "--min-size", "1000", "--max-size", "100"]
        result = main()

        # Should fail with exit code 1
        assert result == 1

        # Should log an error message
        assert "--min-size cannot be greater than --max-size" in caplog.text

    def test_zero_min_size_accepted(self, tmp_path):
        """Test that zero min-size is accepted."""
        # Create a test directory
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Should not raise an error during parsing
        sys.argv = ["dupfinder", str(test_dir), "--min-size", "0"]
        result = main()

        # Should succeed (exit code 0)
        assert result == 0

    def test_zero_max_size_accepted(self, tmp_path):
        """Test that zero max-size is accepted."""
        # Create a test directory
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Should not raise an error during parsing
        sys.argv = ["dupfinder", str(test_dir), "--max-size", "0"]
        result = main()

        # Should succeed (exit code 0)
        assert result == 0

    def test_valid_size_range_accepted(self, tmp_path):
        """Test that valid size range is accepted."""
        # Create a test directory
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Should not raise an error
        sys.argv = ["dupfinder", str(test_dir), "--min-size", "100", "--max-size", "1000"]
        result = main()

        # Should succeed (exit code 0)
        assert result == 0

    def test_equal_min_max_size_accepted(self, tmp_path):
        """Test that min-size == max-size is accepted."""
        # Create a test directory
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Should not raise an error
        sys.argv = ["dupfinder", str(test_dir), "--min-size", "500", "--max-size", "500"]
        result = main()

        # Should succeed (exit code 0)
        assert result == 0

    def test_max_size_none_accepted(self, tmp_path):
        """Test that not providing max-size is accepted."""
        # Create a test directory
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        # Should not raise an error when max_size is None
        sys.argv = ["dupfinder", str(test_dir), "--min-size", "100"]
        result = main()

        # Should succeed (exit code 0)
        assert result == 0

    def test_parse_args_negative_min_size(self, tmp_path):
        """Test that negative min-size can be parsed (validation happens in main)."""
        args = parse_args([str(tmp_path), "--min-size", "-1"])
        assert args.min_size == -1

    def test_parse_args_negative_max_size(self, tmp_path):
        """Test that negative max-size can be parsed (validation happens in main)."""
        args = parse_args([str(tmp_path), "--max-size", "-1"])
        assert args.max_size == -1
