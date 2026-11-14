# dupfinder

A cross-platform CLI tool to find duplicate files using chunked hashing (BLAKE2/xxhash).

[![CI](https://github.com/abrioso/dupfinder/workflows/CI/badge.svg)](https://github.com/abrioso/dupfinder/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

## Features

- 🚀 **Fast chunked hashing** - Uses BLAKE2 or xxhash for efficient duplicate detection
- 🔍 **Smart scanning** - Groups files by size before hashing to minimize I/O
- 🎨 **Multiple output formats** - JSON, CSV, or human-readable table
- 🛡️ **Flexible filtering** - Exclude patterns, .gitignore support, size filters
- 🔗 **Safe operations** - Dry-run mode for delete/hardlink operations
- 📌 **Reference directories and keep policies** - Choose which copy is kept
- 📄 **Equivalent Office documents** - Optional report of `.docx`/`.xlsx`/`.pptx` files with
  the same content, the same text or similar text (never deleted)
- 🕒 **Timestamps** - File and in-document modification times in every output
- ⚡ **Multi-threaded** - Parallel file hashing for better performance
- 🌍 **Cross-platform** - Works on macOS, Linux, and Windows
- 📝 **Type hints & docstrings** - Fully typed and documented codebase

## Installation

### From source

Use an activated virtual environment with Python 3.12 or newer.

```bash
git clone https://github.com/abrioso/dupfinder.git
cd dupfinder
python -m pip install -e .
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

Empty files are skipped by default (`--min-size` defaults to 1). Include them with:

```bash
dupfinder /path/to/dir --min-size 0
```

### Choosing which file to keep

Each group lists the file to keep first. Protect whole directories with `--reference`:
their files are always kept and are never deleted or replaced, even when several of them
are duplicates of each other. Reference directories are scanned even if they are not
listed as scan paths.

```bash
dupfinder ~/Downloads --reference ~/Documents/Official --delete --dry-run
```

When no reference file settles it, `--keep` picks the file to keep:

| Policy | File kept |
|---|---|
| `first` (default) | First path in alphabetical order |
| `oldest` | Oldest modification time |
| `newest` | Newest modification time |
| `shortest-path` | Least nested, then shortest path |

```bash
dupfinder /path/to/dir --keep oldest --delete --dry-run
```

Outputs mark each file with its role: `reference`, `keep` or `duplicate`.

### Equivalent Office documents

Office files (`.docx`, `.xlsx`, `.pptx`) can hold the same document without being
byte-identical. These searches are optional and independent, and their results are
labelled `ficheiro equivalente - nível X (validar)`.

**Equivalent files are only reported. `--delete` and `--hardlink` never touch them.**

| Flag | Level | Finds |
|---|---|---|
| `--equiv-package` | 1 | Same content parts, different metadata or compression |
| `--equiv-text` | 2 | Same text, different formatting |
| `--equiv-similar` | 3 | Similar text, such as successive versions of a document |

```bash
# All three levels, written to a CSV report
dupfinder ~/Documents --equiv-package --equiv-text --equiv-similar \
  --output csv --output-file report.csv

# Level 3 only, with a looser threshold (default: 0.9)
dupfinder ~/Documents --equiv-similar --similarity-threshold 0.8
```

How each level works:

- **Level 1** reads only the ZIP directory of each file (name, CRC and size of each part)
  and ignores `docProps/`, so it adds almost no scan time.
- **Level 2** extracts the text and compares its hash. Word text includes notes, headers
  and footers; PowerPoint text includes speaker notes; Excel text is the sheet names and
  cells in order, with formulas reported instead of their cached results, so two workbooks
  with the same values but different formulas are *not* level 2.
- **Level 3** compares overlapping sequences of four words and groups documents of the
  same type whose similarity reaches the threshold. Each file shows its similarity to the
  first file of the group. For long documents the similarity is an estimate (about ±0.03),
  so pairs very close to the threshold may fall on either side of it.

Exact duplicates are represented by the file to keep, and a pair of files is reported
only once, at the lowest requested level where it matches. Legacy formats (`.doc`, `.xls`,
`.ppt`) and password-protected files are skipped and logged.

Indicative cost on 2,000 Word documents of 3,000 words each (87 MB): 0.2 s for exact
duplicates only, plus about 0.4 s for level 1, 3 s for level 2 and 8 s for level 3.

### Actions

Delete duplicates (keeps the file selected by `--reference`/`--keep`):

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

Every output shows, for each file, its role and its file system modification time. For
`.docx`, `.xlsx` and `.pptx` files it also shows the save time and last author recorded
inside the document, which survive copies and downloads.

### Table format (default)

```
Duplicate group 1 (2 files, 1.50 KB each):
Hash: a1b2c3d4e5f6
Wasted space: 1.50 KB
  - /path/to/report.docx [keep]
      modified: 2026-11-10T17:02:11+00:00 | document saved: 2026-11-10T17:02:09Z by Ana
  - /path/to/copy/report.docx
      modified: 2026-11-12T08:38:00+00:00 | document saved: 2026-11-10T17:02:09Z by Ana

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
      "/path/to/report.docx",
      "/path/to/copy/report.docx"
    ],
    "details": [
      {
        "path": "/path/to/report.docx",
        "role": "keep",
        "size": 1536,
        "modified": "2026-11-10T17:02:11+00:00",
        "document_modified": "2026-11-10T17:02:09Z",
        "document_last_modified_by": "Ana"
      },
      {
        "path": "/path/to/copy/report.docx",
        "role": "duplicate",
        "size": 1536,
        "modified": "2026-11-12T08:38:00+00:00",
        "document_modified": "2026-11-10T17:02:09Z",
        "document_last_modified_by": "Ana"
      }
    ]
  }
]
```

### CSV format

```csv
hash,file_path,group_size,role,size,modified,document_modified,document_last_modified_by
a1b2c3d4e5f6,/path/to/report.docx,2,keep,1536,2026-11-10T17:02:11+00:00,2026-11-10T17:02:09Z,Ana
a1b2c3d4e5f6,/path/to/copy/report.docx,2,duplicate,1536,2026-11-12T08:38:00+00:00,2026-11-10T17:02:09Z,Ana
```

## Development

### Python support policy

- Minimum runtime: **Python 3.12**.
- Reference interpreter for development and quality tools: **Python 3.13**,
  recorded in `.python-version`. Install a current 3.13 patch release.
- CI tests Python **3.12, 3.13, 3.14, and 3.15** on Linux, macOS, and Windows.
- Black and Ruff target **Python 3.12** syntax. Code must not rely on features
  exclusive to newer interpreters while 3.12 remains supported.
- Version **0.2.0** drops Python 3.9, 3.10, and 3.11 support. Upgrade the interpreter
  before installing this version.

Review this policy when adopting a new stable Python release; compatibility with
future versions is only confirmed after their CI jobs pass.

### Setup development environment

On Linux or macOS:

```bash
git clone https://github.com/abrioso/dupfinder.git
cd dupfinder
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pre-commit install
```

On Windows, after cloning the repository, create and activate the environment in
PowerShell with `py -3.13 -m venv .venv` and `.\.venv\Scripts\Activate.ps1`, then run
the same installation and `pre-commit install` commands. Keep Python 3.13 available
for the hooks even when testing the application with another supported interpreter.

### Run tests

The `dev` extra includes the `test` extra. For a test-only environment on any
supported interpreter, install `python -m pip install -e ".[test]"`.

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

CI runs on pushes and pull requests targeting `develop` or `main`. Create working
branches from `develop` and open pull requests against `develop` before promoting
validated changes to `main`.

Black and Ruff are pinned to the same versions in `pyproject.toml` and
`.pre-commit-config.yaml`; update both files together when upgrading these tools.
The test suite enforces a minimum total coverage of 80%. The test matrix installs
only the `test` extra; a separate Python 3.13 job runs all quality hooks, including
Black and Ruff. Linux CI uses Ubuntu 24.04 for a consistent runner baseline.

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

- Python 3.12 or higher (Python 3.13 recommended for development)
- xxhash (optional, for faster hashing)
- pathspec (for .gitignore support)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

- Uses [xxhash](https://github.com/ifduyue/python-xxhash) for fast hashing
- Uses [pathspec](https://github.com/cpburnz/python-pathspec) for gitignore pattern matching
