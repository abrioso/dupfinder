"""Tests for reference directories, keep policies and scan de-duplication."""

import json
import os
import sys

import pytest

from dupfinder.cli import main, parse_args
from dupfinder.formatters import format_csv, format_json, format_table
from dupfinder.scanner import DuplicateFinder


def _write(path, content="same content", mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class TestKeepPolicy:
    """Test cases for choosing which file of a group is kept."""

    def test_default_keeps_first_path(self, tmp_path):
        """The default policy keeps the alphabetically first path."""
        b = _write(tmp_path / "b.txt")
        a = _write(tmp_path / "a.txt")

        groups = DuplicateFinder().find_duplicates([tmp_path])

        assert list(groups.values()) == [[a, b]]

    def test_keep_oldest_and_newest(self, tmp_path):
        """Oldest and newest policies order by modification time."""
        a = _write(tmp_path / "a.txt", mtime=2_000_000_000)
        b = _write(tmp_path / "b.txt", mtime=1_000_000_000)

        oldest = DuplicateFinder(keep="oldest").find_duplicates([tmp_path])
        newest = DuplicateFinder(keep="newest").find_duplicates([tmp_path])

        assert list(oldest.values()) == [[b, a]]
        assert list(newest.values()) == [[a, b]]

    def test_keep_shortest_path(self, tmp_path):
        """Shortest-path policy prefers the least nested file."""
        deep = _write(tmp_path / "a" / "b" / "file.txt")
        shallow = _write(tmp_path / "z.txt")

        groups = DuplicateFinder(keep="shortest-path").find_duplicates([tmp_path])

        assert list(groups.values()) == [[shallow, deep]]

    def test_unknown_policy_rejected(self):
        """An unknown keep policy raises an error."""
        with pytest.raises(ValueError):
            DuplicateFinder(keep="random")


class TestReference:
    """Test cases for reference directories."""

    def test_reference_file_sorts_first(self, tmp_path):
        """A reference file is kept even when the keep policy would pick another."""
        other = _write(tmp_path / "a" / "file.txt", mtime=1_000_000_000)
        ref = _write(tmp_path / "ref" / "file.txt", mtime=2_000_000_000)

        finder = DuplicateFinder(reference_paths=[tmp_path / "ref"], keep="oldest")
        groups = finder.find_duplicates([tmp_path])

        assert list(groups.values()) == [[ref, other]]
        assert finder.is_reference(ref)
        assert not finder.is_reference(other)

    def test_reference_scanned_even_if_not_listed(self, tmp_path):
        """Reference directories are scanned without being passed as scan paths."""
        other = _write(tmp_path / "work" / "file.txt")
        ref = _write(tmp_path / "ref" / "file.txt")

        finder = DuplicateFinder(reference_paths=[tmp_path / "ref"])
        groups = finder.find_duplicates([tmp_path / "work"])

        assert list(groups.values()) == [[ref, other]]

    def test_reference_files_never_deleted(self, tmp_path):
        """Deleting duplicates leaves every reference file in place."""
        ref1 = _write(tmp_path / "ref" / "one.txt")
        ref2 = _write(tmp_path / "ref" / "two.txt")
        other = _write(tmp_path / "work" / "file.txt")

        finder = DuplicateFinder(reference_paths=[tmp_path / "ref"])
        groups = finder.find_duplicates([tmp_path])
        count = finder.delete_duplicates(groups, dry_run=False)

        assert count == 1
        assert ref1.exists() and ref2.exists()
        assert not other.exists()

    def test_reference_only_group_untouched(self, tmp_path):
        """A group made only of reference files is reported but not modified."""
        ref1 = _write(tmp_path / "ref" / "one.txt")
        ref2 = _write(tmp_path / "ref" / "two.txt")

        finder = DuplicateFinder(reference_paths=[tmp_path / "ref"])
        groups = finder.find_duplicates([tmp_path])

        assert len(groups) == 1
        assert finder.delete_duplicates(groups, dry_run=False) == 0
        assert finder.hardlink_duplicates(groups, dry_run=False) == 0
        assert ref1.exists() and ref2.exists()
        assert ref1.stat().st_ino != ref2.stat().st_ino

    def test_reference_files_never_hardlinked(self, tmp_path):
        """Hardlinking replaces only non-reference files."""
        ref1 = _write(tmp_path / "ref" / "one.txt")
        ref2 = _write(tmp_path / "ref" / "two.txt")
        other = _write(tmp_path / "work" / "file.txt")

        finder = DuplicateFinder(reference_paths=[tmp_path / "ref"])
        groups = finder.find_duplicates([tmp_path])
        count = finder.hardlink_duplicates(groups, dry_run=False)

        assert count == 1
        assert ref1.stat().st_ino != ref2.stat().st_ino
        assert other.stat().st_ino == ref1.stat().st_ino

    def test_symlink_inside_reference_is_protected(self, tmp_path):
        """A symlink in a reference directory that points outside it is never modified."""
        target = _write(tmp_path / "elsewhere" / "target.txt")
        copy = _write(tmp_path / "a_work" / "copy.txt")
        link = tmp_path / "z_ref" / "link.txt"
        link.parent.mkdir()
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("symlinks are not available")

        finder = DuplicateFinder(reference_paths=[tmp_path / "z_ref"], follow_symlinks=True)
        groups = finder.find_duplicates([tmp_path / "a_work"])

        assert finder.is_reference(link)
        assert list(groups.values()) == [[link, copy]]
        assert finder.delete_duplicates(groups, dry_run=False) == 1
        assert link.is_symlink() and target.exists()
        assert not copy.exists()


class TestOverlappingPaths:
    """Test cases for scan paths that overlap."""

    def test_same_path_twice_is_not_a_duplicate(self, tmp_path):
        """Scanning the same directory twice must not pair a file with itself."""
        _write(tmp_path / "only.txt")

        groups = DuplicateFinder().find_duplicates([tmp_path, tmp_path])

        assert groups == {}

    def test_nested_paths_do_not_delete_the_only_copy(self, tmp_path):
        """A nested scan path does not cause the single copy to be deleted."""
        only = _write(tmp_path / "sub" / "only.txt")

        finder = DuplicateFinder()
        groups = finder.find_duplicates([tmp_path, tmp_path / "sub"])
        finder.delete_duplicates(groups, dry_run=False)

        assert only.exists()


class TestRoleOutput:
    """Test cases for the role shown by the formatters."""

    def test_roles_in_all_formats(self, tmp_path):
        """Formatters mark the reference, kept and duplicate files."""
        ref = _write(tmp_path / "ref" / "file.txt")
        other = _write(tmp_path / "work" / "file.txt")
        finder = DuplicateFinder(reference_paths=[tmp_path / "ref"])
        groups = finder.find_duplicates([tmp_path])

        data = json.loads(format_json(groups, finder.is_reference))
        assert data[0]["files"] == [str(ref), str(other)]
        assert [d["role"] for d in data[0]["details"]] == ["reference", "duplicate"]

        csv_lines = format_csv(groups, finder.is_reference).strip().splitlines()
        assert csv_lines[0] == "hash,file_path,group_size,role"
        assert csv_lines[1].endswith(",reference")
        assert csv_lines[2].endswith(",duplicate")

        assert f"{ref} [reference]" in format_table(groups, finder.is_reference)

    def test_keep_role_without_reference(self, tmp_path):
        """Without reference directories the first file is marked as kept."""
        a = _write(tmp_path / "a.txt")
        _write(tmp_path / "b.txt")
        groups = DuplicateFinder().find_duplicates([tmp_path])

        assert f"{a} [keep]" in format_table(groups)
        assert [d["role"] for d in json.loads(format_json(groups))[0]["details"]] == [
            "keep",
            "duplicate",
        ]


class TestCLI:
    """Test cases for the new command-line options."""

    def test_parse_reference_and_keep(self, tmp_path):
        """--reference is repeatable and --keep is parsed."""
        args = parse_args(
            [str(tmp_path), "--reference", "a", "--reference", "b", "--keep", "newest"]
        )
        assert [str(p) for p in args.reference] == ["a", "b"]
        assert args.keep == "newest"

    def test_empty_files_ignored_by_default(self, tmp_path, monkeypatch, capsys):
        """Empty files are not reported unless --min-size 0 is given."""
        (tmp_path / "a.txt").touch()
        (tmp_path / "b.txt").touch()

        monkeypatch.setattr(sys, "argv", ["dupfinder", str(tmp_path), "--output", "json"])
        assert main() == 0
        assert capsys.readouterr().out.strip() == ""

        monkeypatch.setattr(
            sys, "argv", ["dupfinder", str(tmp_path), "--output", "json", "--min-size", "0"]
        )
        assert main() == 0
        assert json.loads(capsys.readouterr().out)[0]["count"] == 2

    def test_invalid_reference_rejected(self, tmp_path, monkeypatch):
        """A reference path that is not a directory is an error."""
        monkeypatch.setattr(
            sys, "argv", ["dupfinder", str(tmp_path), "--reference", str(tmp_path / "missing")]
        )
        assert main() == 1

    def test_delete_respects_reference(self, tmp_path, monkeypatch):
        """End to end: --delete keeps the reference copy."""
        ref = _write(tmp_path / "zz_ref" / "file.txt")
        other = _write(tmp_path / "a_work" / "file.txt")

        monkeypatch.setattr(
            sys,
            "argv",
            ["dupfinder", str(tmp_path), "--reference", str(tmp_path / "zz_ref"), "--delete"],
        )
        assert main() == 0
        assert ref.exists()
        assert not other.exists()


class TestHardlinkSymlinkKeeper:
    """Hardlinking when the file to keep is a symlink."""

    def test_duplicates_link_to_the_referent(self, tmp_path):
        """Duplicates become hardlinks of the real file, never copies of the symlink."""
        target = _write(tmp_path / "elsewhere" / "target.txt")
        copy = _write(tmp_path / "a_work" / "copy.txt")
        link = tmp_path / "z_ref" / "link.txt"
        link.parent.mkdir()
        try:
            link.symlink_to(os.path.relpath(target, link.parent))
        except OSError:
            pytest.skip("symlinks are not available")

        finder = DuplicateFinder(reference_paths=[tmp_path / "z_ref"], follow_symlinks=True)
        groups = finder.find_duplicates([tmp_path / "a_work"])

        assert finder.hardlink_duplicates(groups, dry_run=False) == 1
        assert not copy.is_symlink()
        assert copy.read_text() == "same content"
        assert copy.stat().st_ino == target.stat().st_ino
        assert link.is_symlink()
