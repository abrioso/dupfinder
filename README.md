# dupfinder

A cross-platform CLI tool to find duplicate files using chunked hashing (BLAKE2/xxhash).

[![CI](https://github.com/abrioso/dupfinder/workflows/CI/badge.svg)](https://github.com/abrioso/dupfinder/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

## Features

- 🚀 **Fast chunked hashing** - Uses BLAKE2 or xxhash for efficient duplicate detection
- 🔍 **Smart scanning** - Groups files by size before hashing to minimize I/O
- 🎨 **Multiple output formats** - JSON, CSV, or human-readable table
- 🛡️ **Flexible filtering** - Exclude patterns, .gitignore support, size filters
- 🔗 **Safe operations** - Dry-run mode for delete/hardlink operations
- ⚡ **Multi-threaded** - Parallel file hashing for better performance
- 🌍 **Cross-platform** - Works on macOS, Linux, and Windows
- 📝 **Type hints & docstrings** - Fully typed and documented codebase

## Installation

### From source

```bash
git clone https://github.com/abrioso/dupfinder.git
cd dupfinder
pip install -e ".[dev]"
```

### Using pip (once published)

```bash
pip install dupfinder
```

## Usage

### Basic usage

Find duplicates in a directory:

```bash
dupfinder /path/to/directory
```

Find duplicates in multiple paths:

```bash
dupfinder /path/one /path/two /path/three
```

### Output formats

JSON output:

```bash
dupfinder /path/to/dir --output json
```

CSV output:

```bash
dupfinder /path/to/dir --output csv
```

Save output to file:

```bash
dupfinder /path/to/dir --output json --output-file results.json
```

### Hash algorithms

Use BLAKE2 (default: xxhash):

```bash
dupfinder /path/to/dir --hash-algo blake2
```

Use xxhash (faster, requires xxhash package):

```bash
dupfinder /path/to/dir --hash-algo xxhash
```

### Filtering

Filter by file size:

```bash
dupfinder /path/to/dir --min-size 1024 --max-size 1048576
```

Exclude patterns:

```bash
dupfinder /path/to/dir --exclude "*.log" --exclude "*.tmp"
```

Respect .gitignore files:

```bash
dupfinder /path/to/dir --respect-gitignore
```

Follow symbolic links:

```bash
dupfinder /path/to/dir --follow-symlinks
```

### Actions

Delete duplicates (keeps first occurrence):

```bash
dupfinder /path/to/dir --delete --dry-run  # Preview
dupfinder /path/to/dir --delete            # Actually delete
```

Replace duplicates with hardlinks:

```bash
dupfinder /path/to/dir --hardlink --dry-run  # Preview
dupfinder /path/to/dir --hardlink            # Actually hardlink
```

### Performance

Adjust number of threads (default: 4):

```bash
dupfinder /path/to/dir --threads 8
```

### Verbose logging

Enable debug logging:

```bash
dupfinder /path/to/dir --verbose
```

## Examples

### Find and delete duplicates in Downloads folder

```bash
# First, do a dry run to see what would be deleted
dupfinder ~/Downloads --delete --dry-run

# If satisfied, actually delete
dupfinder ~/Downloads --delete
```

### Find large duplicate files and save as JSON

```bash
dupfinder ~/Documents --min-size 1048576 --output json --output-file duplicates.json
```

### Scan project excluding build artifacts

```bash
dupfinder ~/myproject --exclude "node_modules/*" --exclude "*.pyc" --respect-gitignore
```

### Replace duplicates with hardlinks to save space

```bash
dupfinder ~/media --hardlink --dry-run  # Check first
dupfinder ~/media --hardlink            # Apply
```

## Output Examples

### Table format (default)

```
Duplicate group 1 (2 files, 1.50 KB each):
Hash: a1b2c3d4e5f6
Wasted space: 1.50 KB
  - /path/to/file1.txt
  - /path/to/file2.txt

================================================================================
Summary:
  Duplicate groups: 1
  Total duplicate files: 1
  Total wasted space: 1.50 KB
```

### JSON format

```json
[
  {
    "hash": "a1b2c3d4e5f6",
    "count": 2,
    "files": [
      "/path/to/file1.txt",
      "/path/to/file2.txt"
    ]
  }
]
```

### CSV format

```csv
hash,file_path,group_size
a1b2c3d4e5f6,/path/to/file1.txt,2
a1b2c3d4e5f6,/path/to/file2.txt,2
```

## Development

### Setup development environment

```bash
git clone https://github.com/abrioso/dupfinder.git
cd dupfinder
pip install -e ".[dev]"
pre-commit install
```

### Run tests

```bash
pytest
```

Run tests with coverage:

```bash
pytest --cov=dupfinder --cov-report=html
```

### Code formatting

Format code with black:

```bash
black src/ tests/
```

Lint with ruff:

```bash
ruff check src/ tests/
```

### Pre-commit hooks

This project uses pre-commit hooks to ensure code quality:

```bash
pre-commit run --all-files
```

## How it works

1. **Size grouping**: Files are first grouped by size (files with unique sizes can't be duplicates)
2. **Chunk hashing**: Files with matching sizes have their first chunk hashed
3. **Full hashing**: Files with matching chunk hashes are fully hashed
4. **Duplicate detection**: Files with identical full hashes are duplicates

This approach minimizes I/O by only reading full files when necessary.

## Requirements

- Python 3.9 or higher
- xxhash (optional, for faster hashing)
- pathspec (for .gitignore support)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

- Uses [xxhash](https://github.com/ifduyue/python-xxhash) for fast hashing
- Uses [pathspec](https://github.com/cpburnz/python-pathspec) for gitignore pattern matching
