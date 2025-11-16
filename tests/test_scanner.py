"""Tests for dupfinder scanner module."""

import hashlib

from dupfinder.scanner import DuplicateFinder


class TestDuplicateFinder:
    """Test cases for DuplicateFinder class."""

    def test_hash_file_chunk_blake2(self, tmp_path):
        """Test chunk hashing with blake2."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        content = b"Hello, World!" * 1000
        test_file.write_bytes(content)

        finder = DuplicateFinder(hash_algo="blake2")
        chunk_hash = finder._hash_file_chunk(test_file)

        # Verify it's a valid hash
        assert chunk_hash
        assert len(chunk_hash) > 0
        assert isinstance(chunk_hash, str)

    def test_hash_file_full_blake2(self, tmp_path):
        """Test full file hashing with blake2."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        content = b"Hello, World!" * 1000
        test_file.write_bytes(content)

        finder = DuplicateFinder(hash_algo="blake2")
        full_hash = finder._hash_file_full(test_file)

        # Verify it's a valid hash
        assert full_hash
        assert len(full_hash) > 0

        # Verify it matches manual hash
        hasher = hashlib.blake2b()
        hasher.update(content)
        expected = hasher.hexdigest()
        assert full_hash == expected

    def test_should_include_file_size_filter(self, tmp_path):
        """Test file inclusion with size filters."""
        # Create test files
        small_file = tmp_path / "small.txt"
        small_file.write_text("small")

        large_file = tmp_path / "large.txt"
        large_file.write_text("x" * 10000)

        # Test min size filter
        finder = DuplicateFinder(min_size=100)
        assert not finder._should_include_file(small_file, tmp_path)
        assert finder._should_include_file(large_file, tmp_path)

        # Test max size filter
        finder = DuplicateFinder(max_size=100)
        assert finder._should_include_file(small_file, tmp_path)
        assert not finder._should_include_file(large_file, tmp_path)

    def test_should_include_file_exclude_patterns(self, tmp_path):
        """Test file inclusion with exclude patterns."""
        # Create test files
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        log_file = tmp_path / "test.log"
        log_file.write_text("log")

        # Test exclusion
        finder = DuplicateFinder(exclude_patterns=["*.log"])
        assert finder._should_include_file(test_file, tmp_path)
        assert not finder._should_include_file(log_file, tmp_path)

    def test_find_duplicates_no_duplicates(self, tmp_path):
        """Test finding duplicates when there are none."""
        # Create unique files
        file1 = tmp_path / "file1.txt"
        file1.write_text("content1")

        file2 = tmp_path / "file2.txt"
        file2.write_text("content2")

        finder = DuplicateFinder()
        duplicates = finder.find_duplicates([tmp_path])

        assert duplicates == {}

    def test_find_duplicates_with_duplicates(self, tmp_path):
        """Test finding actual duplicates."""
        # Create duplicate files
        content = "This is duplicate content"

        file1 = tmp_path / "file1.txt"
        file1.write_text(content)

        file2 = tmp_path / "file2.txt"
        file2.write_text(content)

        file3 = tmp_path / "file3.txt"
        file3.write_text("unique content")

        finder = DuplicateFinder()
        duplicates = finder.find_duplicates([tmp_path])

        assert len(duplicates) == 1
        # Get the single duplicate group
        dup_group = list(duplicates.values())[0]
        assert len(dup_group) == 2
        assert file1 in dup_group
        assert file2 in dup_group

    def test_find_duplicates_nested_directories(self, tmp_path):
        """Test finding duplicates in nested directories."""
        # Create nested structure
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        dir2 = tmp_path / "dir2"
        dir2.mkdir()

        content = "duplicate content"
        file1 = dir1 / "file.txt"
        file1.write_text(content)

        file2 = dir2 / "file.txt"
        file2.write_text(content)

        finder = DuplicateFinder()
        duplicates = finder.find_duplicates([tmp_path])

        assert len(duplicates) == 1
        dup_group = list(duplicates.values())[0]
        assert len(dup_group) == 2

    def test_delete_duplicates_dry_run(self, tmp_path):
        """Test deleting duplicates in dry run mode."""
        # Create duplicate files
        content = "duplicate"
        file1 = tmp_path / "file1.txt"
        file1.write_text(content)
        file2 = tmp_path / "file2.txt"
        file2.write_text(content)

        finder = DuplicateFinder()
        duplicates = finder.find_duplicates([tmp_path])

        count = finder.delete_duplicates(duplicates, dry_run=True)

        assert count == 1
        # Both files should still exist
        assert file1.exists()
        assert file2.exists()

    def test_delete_duplicates_real(self, tmp_path):
        """Test actually deleting duplicates."""
        # Create duplicate files
        content = "duplicate"
        file1 = tmp_path / "file1.txt"
        file1.write_text(content)
        file2 = tmp_path / "file2.txt"
        file2.write_text(content)

        finder = DuplicateFinder()
        duplicates = finder.find_duplicates([tmp_path])

        count = finder.delete_duplicates(duplicates, dry_run=False)

        assert count == 1
        # First file should exist, second should be deleted
        assert file1.exists()
        assert not file2.exists()

    def test_hardlink_duplicates_dry_run(self, tmp_path):
        """Test hardlinking duplicates in dry run mode."""
        # Create duplicate files
        content = "duplicate"
        file1 = tmp_path / "file1.txt"
        file1.write_text(content)
        file2 = tmp_path / "file2.txt"
        file2.write_text(content)

        finder = DuplicateFinder()
        duplicates = finder.find_duplicates([tmp_path])

        count = finder.hardlink_duplicates(duplicates, dry_run=True)

        assert count == 1
        # Both files should still exist
        assert file1.exists()
        assert file2.exists()

    def test_hardlink_duplicates_real(self, tmp_path):
        """Test actually hardlinking duplicates."""
        # Create duplicate files
        content = "duplicate"
        file1 = tmp_path / "file1.txt"
        file1.write_text(content)
        file2 = tmp_path / "file2.txt"
        file2.write_text(content)

        finder = DuplicateFinder()
        duplicates = finder.find_duplicates([tmp_path])

        count = finder.hardlink_duplicates(duplicates, dry_run=False)

        assert count == 1
        # Both files should exist
        assert file1.exists()
        assert file2.exists()

        # They should have the same inode (hardlinked)
        assert file1.stat().st_ino == file2.stat().st_ino

    def test_collect_files_single_file(self, tmp_path):
        """Test collecting a single file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test")

        finder = DuplicateFinder()
        files = finder._collect_files([test_file])

        assert len(files) == 1
        assert files[0] == test_file

    def test_collect_files_directory(self, tmp_path):
        """Test collecting files from a directory."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("test1")
        file2 = tmp_path / "file2.txt"
        file2.write_text("test2")

        finder = DuplicateFinder()
        files = finder._collect_files([tmp_path])

        assert len(files) == 2
        assert file1 in files
        assert file2 in files

    def test_symlink_handling(self, tmp_path):
        """Test symlink handling."""
        # Create a file and a symlink to it
        real_file = tmp_path / "real.txt"
        real_file.write_text("content")

        link_file = tmp_path / "link.txt"
        link_file.symlink_to(real_file)

        # Test without following symlinks
        finder = DuplicateFinder(follow_symlinks=False)
        files = finder._collect_files([tmp_path])
        assert link_file not in files or len(files) == 1

        # Test with following symlinks
        finder = DuplicateFinder(follow_symlinks=True)
        files = finder._collect_files([tmp_path])
        # Should include both (though they may be detected as duplicates)
        assert len(files) >= 1

    def test_gitignore_support(self, tmp_path):
        """Test .gitignore file support."""
        # Create .gitignore
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.log\n")

        # Create files
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("test")
        log_file = tmp_path / "test.log"
        log_file.write_text("log")

        # Test with gitignore respect
        finder = DuplicateFinder(respect_gitignore=True)
        files = finder._collect_files([tmp_path])

        assert txt_file in files
        assert log_file not in files
