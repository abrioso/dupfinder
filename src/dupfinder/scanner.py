"""File scanning and duplicate detection logic."""

import hashlib
import logging
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

try:
    import xxhash

    HAS_XXHASH = True
except ImportError:
    HAS_XXHASH = False

import pathspec

logger = logging.getLogger(__name__)


class DuplicateFinder:
    """Find duplicate files using chunked hashing."""

    CHUNK_SIZE = 8192  # 8KB chunks for initial hash
    FULL_CHUNK_SIZE = 65536  # 64KB chunks for full hash

    def __init__(
        self,
        hash_algo: str = "xxhash",
        min_size: int = 0,
        max_size: Optional[int] = None,
        exclude_patterns: Optional[list[str]] = None,
        respect_gitignore: bool = False,
        follow_symlinks: bool = False,
        num_threads: int = 4,
    ):
        """Initialize the duplicate finder.

        Args:
            hash_algo: Hash algorithm to use ('blake2' or 'xxhash')
            min_size: Minimum file size in bytes
            max_size: Maximum file size in bytes (None for no limit)
            exclude_patterns: List of glob patterns to exclude
            respect_gitignore: Whether to respect .gitignore files
            follow_symlinks: Whether to follow symbolic links
            num_threads: Number of threads for parallel processing
        """
        if hash_algo == "xxhash" and not HAS_XXHASH:
            logger.warning("xxhash not available, falling back to blake2")
            hash_algo = "blake2"

        self.hash_algo = hash_algo
        self.min_size = min_size
        self.max_size = max_size
        self.exclude_patterns = exclude_patterns or []
        self.respect_gitignore = respect_gitignore
        self.follow_symlinks = follow_symlinks
        self.num_threads = num_threads

        # Create pathspec for exclusion patterns
        self.pathspec = (
            pathspec.PathSpec.from_lines(
                pathspec.patterns.GitWildMatchPattern, self.exclude_patterns
            )
            if self.exclude_patterns
            else None
        )

    def _hash_file_chunk(self, filepath: Path, chunk_size: int = CHUNK_SIZE) -> str:
        """Hash the first chunk of a file.

        Args:
            filepath: Path to the file
            chunk_size: Size of chunk to read

        Returns:
            Hex digest of the chunk hash
        """
        if self.hash_algo == "xxhash":
            hasher = xxhash.xxh64()
        else:
            hasher = hashlib.blake2b()

        try:
            with open(filepath, "rb") as f:
                chunk = f.read(chunk_size)
                hasher.update(chunk)
            return hasher.hexdigest()
        except OSError as e:
            logger.warning(f"Cannot read {filepath}: {e}")
            return ""

    def _hash_file_full(self, filepath: Path) -> str:
        """Hash the entire file.

        Args:
            filepath: Path to the file

        Returns:
            Hex digest of the full file hash
        """
        if self.hash_algo == "xxhash":
            hasher = xxhash.xxh64()
        else:
            hasher = hashlib.blake2b()

        try:
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(self.FULL_CHUNK_SIZE)
                    if not chunk:
                        break
                    hasher.update(chunk)
            return hasher.hexdigest()
        except OSError as e:
            logger.warning(f"Cannot read {filepath}: {e}")
            return ""

    def _should_include_file(self, filepath: Path, root_path: Path) -> bool:
        """Check if a file should be included in the scan.

        Args:
            filepath: Path to the file
            root_path: Root path being scanned

        Returns:
            True if file should be included, False otherwise
        """
        # Check if it's a file
        try:
            if self.follow_symlinks:
                is_file = filepath.is_file()
            else:
                is_file = filepath.is_file() and not filepath.is_symlink()

            if not is_file:
                return False
        except OSError:
            return False

        # Check size constraints
        try:
            size = filepath.stat().st_size
            if size < self.min_size:
                return False
            if self.max_size is not None and size > self.max_size:
                return False
        except OSError:
            return False

        # Check exclusion patterns
        if self.pathspec:
            try:
                rel_path = filepath.relative_to(root_path)
                if self.pathspec.match_file(str(rel_path)):
                    return False
            except ValueError:
                # File is not relative to root_path; skip exclusion check
                pass

        return True

    def _load_gitignore(self, directory: Path) -> Optional[pathspec.PathSpec]:
        """Load .gitignore patterns from a directory.

        Args:
            directory: Directory to check for .gitignore

        Returns:
            PathSpec object or None if no .gitignore found
        """
        gitignore_path = directory / ".gitignore"
        if gitignore_path.is_file():
            try:
                with open(gitignore_path, encoding="utf-8") as f:
                    patterns = f.read().splitlines()
                return pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, patterns)
            except OSError as e:
                logger.warning(f"Cannot read {gitignore_path}: {e}")
        return None

    def _scan_directory(self, path: Path) -> list[Path]:
        """Recursively scan a directory for files.

        Args:
            path: Directory path to scan

        Returns:
            List of file paths
        """
        files = []
        gitignore_specs: dict[Path, pathspec.PathSpec] = {}

        try:
            for root, dirs, filenames in os.walk(path, followlinks=self.follow_symlinks):
                root_path = Path(root)

                # Load .gitignore if needed
                if self.respect_gitignore:
                    gitignore_spec = self._load_gitignore(root_path)
                    if gitignore_spec:
                        gitignore_specs[root_path] = gitignore_spec

                # Filter files
                for filename in filenames:
                    filepath = root_path / filename

                    # Check if file should be included
                    if not self._should_include_file(filepath, path):
                        continue

                    # Check .gitignore
                    if self.respect_gitignore and gitignore_specs:
                        excluded = False
                        # Start from current directory and work up to the scan root
                        check_path = root_path
                        while True:
                            if check_path in gitignore_specs:
                                try:
                                    rel_path = filepath.relative_to(check_path)
                                    if gitignore_specs[check_path].match_file(str(rel_path)):
                                        excluded = True
                                        break
                                except ValueError:
                                    pass
                            if check_path == path:
                                break
                            check_path = check_path.parent
                        if excluded:
                            continue

                    files.append(filepath)

        except OSError as e:
            logger.warning(f"Cannot scan {path}: {e}")

        return files

    def _collect_files(self, paths: list[Path]) -> list[Path]:
        """Collect all files from the given paths.

        Args:
            paths: List of file or directory paths

        Returns:
            List of file paths
        """
        all_files = []

        for path in paths:
            if path.is_file():
                if self._should_include_file(path, path.parent):
                    all_files.append(path)
            elif path.is_dir():
                all_files.extend(self._scan_directory(path))
            else:
                logger.warning(f"Skipping {path}: not a file or directory")

        return all_files

    def find_duplicates(self, paths: list[Path]) -> dict[str, list[Path]]:
        """Find duplicate files in the given paths.

        Args:
            paths: List of paths to scan

        Returns:
            Dictionary mapping hash to list of duplicate file paths
        """
        logger.info("Collecting files...")
        files = self._collect_files(paths)
        logger.info(f"Found {len(files)} files to process")

        if not files:
            return {}

        # Group files by size first (optimization)
        logger.debug("Grouping files by size...")
        size_groups: dict[int, list[Path]] = defaultdict(list)
        for filepath in files:
            try:
                size = filepath.stat().st_size
                size_groups[size].append(filepath)
            except OSError as e:
                logger.warning(f"Cannot stat {filepath}: {e}")

        # Filter out unique sizes
        potential_duplicates = []
        for size, file_list in size_groups.items():
            if len(file_list) > 1:
                potential_duplicates.extend(file_list)

        logger.info(f"Found {len(potential_duplicates)} files with duplicate sizes")

        if not potential_duplicates:
            return {}

        # Hash first chunk of files with same size
        logger.debug("Hashing file chunks...")
        chunk_hash_groups: dict[str, list[Path]] = defaultdict(list)

        with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            future_to_file = {
                executor.submit(self._hash_file_chunk, f): f for f in potential_duplicates
            }

            for future in as_completed(future_to_file):
                filepath = future_to_file[future]
                try:
                    chunk_hash = future.result()
                    if chunk_hash:
                        chunk_hash_groups[chunk_hash].append(filepath)
                except Exception as e:
                    logger.warning(f"Error hashing chunk of {filepath}: {e}")

        # Get files that have matching chunk hashes
        potential_duplicates = []
        for chunk_hash, file_list in chunk_hash_groups.items():
            if len(file_list) > 1:
                potential_duplicates.extend(file_list)

        logger.info(f"Found {len(potential_duplicates)} files with matching chunk hashes")

        if not potential_duplicates:
            return {}

        # Hash full files
        logger.debug("Hashing full files...")
        full_hash_groups: dict[str, list[Path]] = defaultdict(list)

        with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            future_to_file = {
                executor.submit(self._hash_file_full, f): f for f in potential_duplicates
            }

            for future in as_completed(future_to_file):
                filepath = future_to_file[future]
                try:
                    full_hash = future.result()
                    if full_hash:
                        full_hash_groups[full_hash].append(filepath)
                except Exception as e:
                    logger.warning(f"Error hashing {filepath}: {e}")

        # Filter to only actual duplicates
        duplicates = {
            hash_val: sorted(file_list, key=str)
            for hash_val, file_list in full_hash_groups.items()
            if len(file_list) > 1
        }

        logger.info(f"Found {len(duplicates)} groups of duplicate files")

        return duplicates

    def delete_duplicates(self, duplicates: dict[str, list[Path]], dry_run: bool = True) -> int:
        """Delete duplicate files, keeping the first occurrence.

        Args:
            duplicates: Dictionary of duplicate file groups
            dry_run: If True, don't actually delete files

        Returns:
            Number of files deleted (or would be deleted)
        """
        count = 0
        for hash_val, file_list in duplicates.items():
            # Keep first file, delete the rest
            for filepath in file_list[1:]:
                if dry_run:
                    logger.info(f"Would delete: {filepath}")
                    count += 1
                else:
                    try:
                        filepath.unlink()
                        logger.info(f"Deleted: {filepath}")
                        count += 1
                    except OSError as e:
                        logger.error(f"Cannot delete {filepath}: {e}")
                        continue
        return count

    def hardlink_duplicates(self, duplicates: dict[str, list[Path]], dry_run: bool = True) -> int:
        """Replace duplicate files with hardlinks to the first occurrence.

        Args:
            duplicates: Dictionary of duplicate file groups
            dry_run: If True, don't actually create hardlinks

        Returns:
            Number of hardlinks created (or would be created)
        """
        count = 0
        for hash_val, file_list in duplicates.items():
            original = file_list[0]
            for filepath in file_list[1:]:
                # Check if files are already hardlinked (same inode)
                try:
                    if original.stat().st_ino == filepath.stat().st_ino:
                        logger.debug(f"Skipping already hardlinked: {filepath} -> {original}")
                        continue
                except OSError as e:
                    logger.warning(f"Cannot stat {filepath}: {e}")
                    continue

                if dry_run:
                    logger.info(f"Would hardlink: {filepath} -> {original}")
                    count += 1
                else:
                    try:
                        # Create hardlink with temporary name
                        temp_path = filepath.with_suffix(filepath.suffix + f".tmp.{os.getpid()}")
                        os.link(original, temp_path)
                        # Atomically replace the original file
                        temp_path.replace(filepath)
                        logger.info(f"Hardlinked: {filepath} -> {original}")
                        count += 1
                    except OSError as e:
                        logger.error(f"Cannot hardlink {filepath}: {e}")
        return count
