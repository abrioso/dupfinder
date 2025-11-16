# Copilot Instructions for dupfinder

## Project Overview

dupfinder is a cross-platform CLI tool for finding duplicate files using chunked hashing (BLAKE2/xxhash). The project is built with Python and focuses on performance, accuracy, and user-friendly output.

**Key Features:**
- Fast chunked hashing for efficient duplicate detection
- Smart file scanning with size-based grouping
- Multiple output formats (JSON, CSV, table)
- Flexible filtering with .gitignore support
- Safe operations with dry-run mode
- Multi-threaded file hashing
- Cross-platform support (macOS, Linux, Windows)

## Project Structure

```
dupfinder/
├── src/dupfinder/          # Main source code
│   ├── __init__.py         # Package initialization
│   ├── __main__.py         # Entry point for python -m dupfinder
│   ├── cli.py              # Command-line interface and argument parsing
│   ├── scanner.py          # Core duplicate detection logic
│   └── formatters.py       # Output formatting (JSON, CSV, table)
├── tests/                  # Test suite
│   ├── test_cli.py         # CLI tests
│   ├── test_formatters.py  # Formatter tests
│   └── test_scanner.py     # Scanner tests
├── pyproject.toml          # Project configuration and dependencies
├── .pre-commit-config.yaml # Pre-commit hooks configuration
└── README.md               # Documentation
```

## Code Guidelines

### Python Version
- Target Python 3.9+ (minimum supported version)
- Use modern Python features available in 3.9+
- Type hints are required for all function signatures

### Code Style
- **Line length**: Maximum 100 characters (configured in pyproject.toml)
- **Formatter**: Use Black with line-length=100
- **Linter**: Use Ruff with rules E, F, I, N, W, UP
- **Type hints**: All functions must have complete type annotations
- **Docstrings**: Use Google-style docstrings for all public functions and classes

### Type Hints
```python
# ✅ Good - Complete type annotations
def process_files(paths: list[Path], min_size: int = 0) -> dict[str, list[Path]]:
    """Process files and group by hash."""
    ...

# ❌ Bad - Missing type hints
def process_files(paths, min_size=0):
    ...
```

### Docstrings
```python
# ✅ Good - Google-style docstring
def find_duplicates(self, paths: list[Path]) -> dict[str, list[Path]]:
    """Find duplicate files in the given paths.

    Args:
        paths: List of directories or files to scan

    Returns:
        Dictionary mapping file hashes to lists of duplicate file paths

    Raises:
        ValueError: If paths is empty or contains non-existent paths
    """
    ...
```

### Import Organization
- Standard library imports first
- Third-party imports second
- Local imports last
- Organize alphabetically within each group
- Use Ruff's isort integration (I rule)

### Naming Conventions
- Classes: `PascalCase` (e.g., `DuplicateFinder`)
- Functions/methods: `snake_case` (e.g., `find_duplicates`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `CHUNK_SIZE`)
- Private methods: prefix with `_` (e.g., `_hash_chunk`)

## Testing Requirements

### Test Framework
- Use pytest as the testing framework
- Minimum 80% code coverage required
- All new features must include tests

### Test Structure
- Place tests in the `tests/` directory
- Name test files `test_*.py`
- Name test classes `Test*`
- Name test functions `test_*`
- Use fixtures for common test data and setup

### Running Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=dupfinder --cov-report=html

# Run specific test file
pytest tests/test_scanner.py

# Run with verbose output
pytest -v
```

### Test Examples
```python
# ✅ Good - Clear test name and structure
def test_find_duplicates_with_duplicates(self, tmp_path):
    """Test that duplicate files are correctly identified."""
    # Arrange - Create test files
    file1 = tmp_path / "file1.txt"
    file2 = tmp_path / "file2.txt"
    file1.write_text("duplicate content")
    file2.write_text("duplicate content")
    
    # Act - Find duplicates
    finder = DuplicateFinder()
    duplicates = finder.find_duplicates([tmp_path])
    
    # Assert - Verify results
    assert len(duplicates) == 1
    assert len(list(duplicates.values())[0]) == 2
```

## Building and Linting

### Installation
```bash
# Install in development mode
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Code Formatting
```bash
# Format all code with Black
black src/ tests/

# Check formatting without changes
black --check src/ tests/
```

### Linting
```bash
# Run Ruff linter
ruff check src/ tests/

# Auto-fix issues
ruff check --fix src/ tests/
```

### Pre-commit Hooks
```bash
# Run all pre-commit hooks
pre-commit run --all-files
```

The pre-commit hooks will automatically:
- Remove trailing whitespace
- Fix end-of-file issues
- Check YAML/TOML syntax
- Run Black formatter
- Run Ruff linter with auto-fix

## Security Practices

### File Operations
- Always validate file paths before operations
- Use `Path` objects from `pathlib` instead of string manipulation
- Never follow symlinks by default (make it opt-in via `--follow-symlinks`)
- Implement dry-run mode for destructive operations (delete, hardlink)

### Error Handling
- Handle file permission errors gracefully
- Log errors but continue processing other files
- Provide clear error messages to users
- Never expose internal file paths in error messages to untrusted users

### Input Validation
- Validate all user inputs (paths, sizes, patterns)
- Sanitize glob patterns before use
- Check file size limits to prevent memory issues

## Common Patterns

### Chunked Hashing
The project uses a two-stage hashing approach for efficiency:
1. Hash first chunk (8KB) to quickly eliminate non-duplicates
2. Hash full file only for files with matching chunk hashes

```python
# Example pattern used in scanner.py
def _hash_file_chunk(self, filepath: Path) -> str:
    """Hash the first chunk of a file."""
    with open(filepath, "rb") as f:
        chunk = f.read(self.CHUNK_SIZE)
        return self._hash_data(chunk)

def _hash_file_full(self, filepath: Path) -> str:
    """Hash the entire file."""
    with open(filepath, "rb") as f:
        while chunk := f.read(self.FULL_CHUNK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()
```

### Multi-threading
Use `ThreadPoolExecutor` for I/O-bound operations:

```python
with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
    futures = {executor.submit(process_file, f): f for f in files}
    for future in as_completed(futures):
        result = future.result()
```

### Logging
- Use the logging module, not print statements
- Log at appropriate levels (DEBUG, INFO, WARNING, ERROR)
- Include context in log messages

```python
# ✅ Good
logger.debug(f"Hashing file: {filepath}")
logger.info(f"Found {len(duplicates)} duplicate groups")
logger.error(f"Failed to read file {filepath}: {error}")

# ❌ Bad
print(f"Hashing {filepath}")
```

## Output Formats

Support three output formats:
- **table** (default): Human-readable table format
- **json**: Machine-readable JSON format
- **csv**: CSV format for spreadsheet import

Always implement new formatters in `formatters.py` and add corresponding tests.

## Dependencies

### Required
- `xxhash>=3.0.0`: Fast hashing algorithm
- `pathspec>=0.11.0`: .gitignore pattern matching

### Development
- `pytest>=7.0.0`: Testing framework
- `pytest-cov>=4.0.0`: Coverage reporting
- `black>=23.0.0`: Code formatter
- `ruff>=0.1.0`: Fast Python linter
- `pre-commit>=3.0.0`: Pre-commit hook management

### Adding New Dependencies
1. Add to `pyproject.toml` under appropriate section
2. Update documentation if user-facing
3. Ensure compatibility with Python 3.9+
4. Consider platform compatibility (Windows, macOS, Linux)

## CLI Design

### Argument Naming
- Use lowercase with hyphens (e.g., `--hash-algo`, not `--hash_algo`)
- Provide clear help text for all arguments
- Use sensible defaults
- Make destructive operations require explicit flags

### Error Messages
- Be specific and helpful
- Suggest corrective actions when possible
- Use consistent formatting

```python
# ✅ Good
logger.error(f"Path does not exist: {path}. Please check the path and try again.")

# ❌ Bad
logger.error("Invalid path")
```

## Performance Considerations

- Group files by size before hashing (files with unique sizes can't be duplicates)
- Use chunked hashing to minimize I/O
- Implement multi-threading for I/O-bound operations
- Default to 4 threads, allow user configuration
- Use appropriate chunk sizes (8KB for initial, 64KB for full hash)

## Documentation

- Keep README.md up to date with features and usage examples
- Document all public APIs with docstrings
- Include examples in docstrings for complex functions
- Update CHANGELOG for user-facing changes (if implemented)

## Don't Do

- ❌ Don't use `print()` for logging - use the `logging` module
- ❌ Don't hard-code file paths - use `Path` objects
- ❌ Don't ignore errors silently - log them appropriately
- ❌ Don't break backward compatibility without version bump
- ❌ Don't add dependencies without justification
- ❌ Don't commit code without running pre-commit hooks
- ❌ Don't merge code with test coverage below 80%
- ❌ Don't use string concatenation for file paths - use `Path` / operator

## Git Workflow

- Write clear, descriptive commit messages
- Keep commits focused and atomic
- Run tests before committing
- Use pre-commit hooks (they run automatically)
- Ensure CI passes before merging

## Questions or Clarifications

If you need clarification on any aspect of the codebase:
1. Check the README.md for usage documentation
2. Review existing code for patterns and conventions
3. Look at tests for examples of expected behavior
4. Check pyproject.toml for configuration details
