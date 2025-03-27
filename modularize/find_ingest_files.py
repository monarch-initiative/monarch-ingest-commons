# ruff: noqa: S603, S607

import os
import subprocess
from functools import cache
from pathlib import Path

import typer


def find_git_files(
    ingest_repo_directory: Path,
    path: Path,
) -> set[str]:
    """
    Find all git files from the version history for a file or directory.
    """
    git_filename = os.path.relpath(path, start=ingest_repo_directory)

    proc = subprocess.run(
        [
            "git",
            f"--git-dir={ingest_repo_directory}/.git",
            "log",
            "--name-only",
            "--pretty=format:",
            "--",
            git_filename,
        ],
        capture_output=True,
        text=True,
    )
    return {filename for filename in proc.stdout.split("\n") if filename}


def get_most_recent_files(
    ingest_repo_directory: Path,
    ingest_tag: str,
    follow_renames: bool = True,
    quiet: bool = False,
) -> list[str]:
    """
    Find the most recent names of files for an ingest.
    """
    ingest_src_directories = [
        Path(ingest_repo_directory) / "src/monarch_ingest/ingests" / ingest_tag,
        Path(ingest_repo_directory) / "tests/unit" / ingest_tag,
    ]

    ingest_documentation = ingest_repo_directory / f"docs/Sources/{ingest_tag}.md"
    last_known_filenames: set[str] = set()

    for directory in ingest_src_directories:
        last_known_filenames |= find_git_files(ingest_repo_directory, directory)

    last_known_filenames |= find_git_files(ingest_repo_directory, ingest_documentation)

    if follow_renames:
        filenames = get_filename_history(ingest_repo_directory, list(last_known_filenames))
    else:
        filenames = list(sorted(last_known_filenames))

    if not quiet:
        for filename in filenames:
            print(filename)

    return list(filenames)


def get_filename_history(
    ingest_repo_directory: Path,
    files: list[str],
) -> list[str]:
    """
    Get the history of a set of files, following renames.
    """
    past_git_filenames: set[str] = set()

    for filename in files:
        past_git_filenames |= get_past_filenames(ingest_repo_directory, filename)

    sorted_filenames = sorted(
        past_git_filenames,
        key=lambda f: get_last_modified_date(ingest_repo_directory, f),
    )

    return sorted_filenames


@cache
def get_last_modified_date(
    ingest_repo_directory: Path,
    filename: str,
) -> str:
    """
    Get the date at which a file was last modified in git.
    """
    proc = subprocess.run(
        [
            "git",
            f"--git-dir={ingest_repo_directory}/.git",
            "log",
            "-1",
            "--pretty=format:%ci",
            "--",
            filename,
        ],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def get_past_filenames(
    ingest_git_directory: Path,
    filename: str,
) -> set[str]:
    """
    Get the history of an individual file, following renames.
    """
    proc = subprocess.run(
        [
            "git",
            "--no-pager",
            f"--git-dir={ingest_git_directory}/.git",
            "log",
            "-M80",  # Use an 80% similarity threshold to detect renames
            "--pretty=format:",  # Output nothing to describe the commit
            "--name-only",  # Output the name of the files changed
            "--follow",
            "--",
            filename,
        ],
        capture_output=True,
        text=True,
    )
    return {filename for filename in proc.stdout.split("\n") if filename}


if __name__ == "__main__":
    typer.run(get_most_recent_files)
