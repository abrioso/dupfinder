"""Command-line interface for dupfinder."""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from dupfinder.formatters import format_output
from dupfinder.scanner import DuplicateFinder


def setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity level.

    Args:
        verbose: If True, set log level to DEBUG, otherwise INFO
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args(args: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        args: List of arguments to parse, defaults to sys.argv[1:]

    Returns:
        Parsed arguments namespace
    """
    parser = argparse.ArgumentParser(
        description="Find duplicate files using chunked hashing (BLAKE2/xxhash)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Positional arguments
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Paths to scan for duplicate files",
    )

    # Hash algorithm
    parser.add_argument(
        "--hash-algo",
        choices=["blake2", "xxhash"],
        default="xxhash",
        help="Hash algorithm to use (default: xxhash)",
    )

    # Output format
    parser.add_argument(
        "--output",
        "-o",
        choices=["json", "csv", "table"],
        default="table",
        help="Output format (default: table)",
    )

    parser.add_argument(
        "--output-file",
        "-f",
        type=Path,
        help="Write output to file instead of stdout",
    )

    # Filtering options
    parser.add_argument(
        "--min-size",
        type=int,
        default=0,
        help="Minimum file size in bytes (default: 0)",
    )

    parser.add_argument(
        "--max-size",
        type=int,
        help="Maximum file size in bytes",
    )

    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude patterns (can be specified multiple times)",
    )

    parser.add_argument(
        "--respect-gitignore",
        action="store_true",
        help="Respect .gitignore files",
    )

    # Symlinks
    parser.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="Follow symbolic links",
    )

    # Actions
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete duplicate files (keeps first occurrence)",
    )

    parser.add_argument(
        "--hardlink",
        action="store_true",
        help="Replace duplicates with hardlinks",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Perform dry run (show what would be done without doing it)",
    )

    # Performance
    parser.add_argument(
        "--threads",
        "-t",
        type=int,
        default=4,
        help="Number of threads for parallel processing (default: 4)",
    )

    # Verbosity
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser.parse_args(args)


def main() -> int:
    """Main entry point for the CLI.

    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    args = parse_args()
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    try:
        # Validate size arguments
        if args.min_size < 0:
            logger.error("--min-size must be non-negative")
            return 1
        if args.max_size is not None and args.max_size < 0:
            logger.error("--max-size must be non-negative")
            return 1
        if args.max_size is not None and args.min_size > args.max_size:
            logger.error("--min-size cannot be greater than --max-size")
            return 1

        # Validate paths
        for path in args.paths:
            if not path.exists():
                logger.error(f"Path does not exist: {path}")
                return 1

        # Check for conflicting options
        if args.delete and args.hardlink:
            logger.error("Cannot use both --delete and --hardlink")
            return 1

        if (args.delete or args.hardlink) and not args.dry_run:
            logger.warning("Running without --dry-run. This will modify files!")

        # Create duplicate finder
        finder = DuplicateFinder(
            hash_algo=args.hash_algo,
            min_size=args.min_size,
            max_size=args.max_size,
            exclude_patterns=args.exclude,
            respect_gitignore=args.respect_gitignore,
            follow_symlinks=args.follow_symlinks,
            num_threads=args.threads,
        )

        # Find duplicates
        logger.info("Scanning for duplicate files...")
        duplicates = finder.find_duplicates(args.paths)

        if not duplicates:
            logger.info("No duplicates found")
            return 0

        # Format and output results
        output = format_output(duplicates, format_type=args.output)

        if args.output_file:
            args.output_file.write_text(output)
            logger.info(f"Output written to {args.output_file}")
        else:
            print(output)

        # Perform actions if requested
        if args.delete:
            count = finder.delete_duplicates(duplicates, dry_run=args.dry_run)
            logger.info(f"{'Would delete' if args.dry_run else 'Deleted'} {count} duplicate files")
        elif args.hardlink:
            count = finder.hardlink_duplicates(duplicates, dry_run=args.dry_run)
            logger.info(f"{'Would create' if args.dry_run else 'Created'} {count} hardlinks")

        return 0

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=args.verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())
