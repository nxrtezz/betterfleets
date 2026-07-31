from __future__ import annotations

import argparse
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


BASE_A = Path(r"C:\Users\n03lh\Downloads\_betterfleet\betterfleet")
BASE_B = Path(r"Z:\betterfleets\betterfleet")

WORKERS = 8

# Default ongoing sync scope: the frequently edited project paths.
DEFAULT_FREQ_PATHS = (
    ".dockerignore",
    ".github",
    ".gitignore",
    ".parcelrc",
    ".pre-commit-config.yaml",
    ".prettierrc.json",
    ".python-version",
    "README.md",
    "accounts",
    "api",
    "babel.config.js",
    "biome.jsonc",
    "buses",
    "busstops",
    "bustimes",
    "config",
    "departures",
    "disruptions",
    "docker-compose.yml",
    "Dockerfile",
    "docs",
    "email_obfuscator",
    "fares",
    "fixtures",
    "fly.toml",
    "frontend",
    "gunicorn.conf.py",
    "import.sh",
    "jest.config.js",
    "manage.py",
    "package-lock.json",
    "package.json",
    "photos",
    "pyproject.toml",
    "scripts",
    "services",
    "setup_train_tracking.md",
    "tsconfig.json",
    "uv.lock",
    "vehicles",
)

SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".parcel-cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
SKIP_FILE_SUFFIXES = {".pyc", ".pyo"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare files in C:\\Users\\n03lh\\Downloads\\_betterfleet\\betterfleet "
            "against Z:\\betterfleets\\betterfleet and copy changed/missing files "
            "from C to Z."
        )
    )
    parser.add_argument(
        "subdir",
        nargs="?",
        default=None,
        help=(
            "Optional subdirectory/file to compare, relative to both roots. "
            "If omitted, syncs frequently edited project paths."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report changes without copying files.",
    )
    parser.add_argument(
        "--first-match",
        action="store_true",
        help=(
            "Do an initial full-tree sync so both directories become a complete "
            "match. Without this flag, only frequently edited paths are compared."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=WORKERS,
        help=f"Number of comparison workers. Default: {WORKERS}.",
    )
    migration_group = parser.add_mutually_exclusive_group()
    migration_group.add_argument(
        "--include-migrations",
        dest="include_migrations",
        action="store_true",
        default=True,
        help="Include Django migration directories. This is the default.",
    )
    migration_group.add_argument(
        "--skip-migrations",
        dest="include_migrations",
        action="store_false",
        help="Skip Django migration directories.",
    )
    parser.add_argument(
        "--include-reference",
        action="store_true",
        help="Include bustimes_REFERENCE and TransportStatistics_REFERENCE.",
    )
    return parser.parse_args()


def selected_roots(subdir: str | None, *, first_match: bool) -> tuple[Path, ...]:
    if subdir:
        return (Path(subdir),)
    if first_match:
        return (Path("."),)
    return tuple(Path(path) for path in DEFAULT_FREQ_PATHS)


def should_skip_path_parts(
    parts: tuple[str, ...],
    *,
    include_migrations: bool,
    include_reference: bool,
) -> bool:
    lowered = [part.lower() for part in parts]
    if any(part in SKIP_DIRS for part in lowered):
        return True
    if not include_migrations and "migrations" in lowered:
        return True
    if not include_reference and (
        "bustimes_reference" in lowered
        or "transportstatistics_reference" in lowered
    ):
        return True
    return False


def should_skip_file(
    path: Path,
    *,
    include_migrations: bool,
    include_reference: bool,
) -> bool:
    if should_skip_path_parts(
        path.parts,
        include_migrations=include_migrations,
        include_reference=include_reference,
    ):
        return True
    return path.suffix.lower() in SKIP_FILE_SUFFIXES


def iter_files(
    root: Path,
    *,
    include_migrations: bool,
    include_reference: bool,
):
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    rel = path.relative_to(root)

                    if entry.is_dir(follow_symlinks=False):
                        if should_skip_path_parts(
                            rel.parts,
                            include_migrations=include_migrations,
                            include_reference=include_reference,
                        ):
                            continue
                        stack.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        if should_skip_file(
                            rel,
                            include_migrations=include_migrations,
                            include_reference=include_reference,
                        ):
                            continue
                        yield path
        except OSError as exc:
            print(f"[ERROR WALKING] {current}: {exc}", file=sys.stderr)


def iter_selected_files(
    base: Path,
    roots: tuple[Path, ...],
    *,
    include_migrations: bool,
    include_reference: bool,
):
    for rel_root in roots:
        root = base / rel_root
        if not root.exists():
            print(f"[SKIP MISSING IN A] {rel_root.as_posix()}")
            continue
        if root.is_file():
            if not should_skip_file(
                rel_root,
                include_migrations=include_migrations,
                include_reference=include_reference,
            ):
                yield root, rel_root
            continue
        for path in iter_files(
            root,
            include_migrations=include_migrations,
            include_reference=include_reference,
        ):
            yield path, rel_root / path.relative_to(root)


def compare_file(
    rel_str: str,
    a_path: Path,
    b_path: Path,
):
    try:
        if not b_path.exists():
            return ("MISSING_IN_B", rel_str, a_path, b_path)

        a_stat = a_path.stat()
        b_stat = b_path.stat()

        # Primary sync factor: last modified time
        if a_stat.st_mtime_ns != b_stat.st_mtime_ns:
            return ("DIFFERENT_MTIME", rel_str, a_path, b_path)

        # Secondary check: file size (only if modification times match)
        if a_stat.st_size != b_stat.st_size:
            return ("DIFFERENT_SIZE", rel_str, a_path, b_path)

        # Files are identical (same mtime and size)
        return None
    except OSError as exc:
        return ("ERROR", f"{rel_str} [ERROR: {exc}]", a_path, b_path)


def copy_a_to_b(a_path: Path, b_path: Path) -> None:
    b_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(a_path, b_path)


def main() -> int:
    args = parse_args()
    roots = selected_roots(args.subdir, first_match=args.first_match)

    print(f"A: {BASE_A}")
    print(f"B: {BASE_B}")
    if args.subdir:
        print(f"Scope: {args.subdir}")
    elif args.first_match:
        print("Scope: full directory tree (--first-match)")
    else:
        print("Scope: frequently edited project paths")

    if not BASE_A.exists():
        raise SystemExit(f"Directory A root does not exist: {BASE_A}")
    if not BASE_B.exists():
        raise SystemExit(f"Directory B root does not exist: {BASE_B}")

    jobs = []
    selected = iter_selected_files(
        BASE_A,
        roots,
        include_migrations=args.include_migrations,
        include_reference=args.include_reference,
    )
    for count, (a_path, rel) in enumerate(selected, start=1):
        if should_skip_file(
            rel,
            include_migrations=args.include_migrations,
            include_reference=args.include_reference,
        ):
            continue
        rel_str = rel.as_posix()
        jobs.append((rel_str, a_path, BASE_B / rel))

        if count % 1000 == 0:
            print(f"Queued {count} files...")

    changes = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = executor.map(
            lambda job: compare_file(*job),
            jobs,
            chunksize=50,
        )
        for result in results:
            if result:
                changes.append(result)

    for kind, rel_or_msg, _a_path, _b_path in changes:
        if kind == "MISSING_IN_B":
            print(f"{rel_or_msg} [MISSING IN B]")
        elif kind == "DIFFERENT_SIZE":
            print(f"{rel_or_msg} [DIFFERENT SIZE]")
        elif kind == "DIFFERENT_MTIME":
            print(f"{rel_or_msg} [DIFFERENT LAST EDIT TIME]")
        else:
            print(rel_or_msg)

    if args.dry_run:
        print(f"\nDry run complete. {len(changes)} changed/missing/error result(s).")
        return 0

    print("\nCopying changed/missing files from A to B...\n")
    copied = 0
    errors = 0
    for kind, rel_or_msg, a_path, b_path in changes:
        if kind not in {"MISSING_IN_B", "DIFFERENT_SIZE", "DIFFERENT_MTIME"}:
            errors += 1
            continue
        try:
            copy_a_to_b(a_path, b_path)
            copied += 1
            print(f"{rel_or_msg} [COPIED A -> B]")
        except OSError as exc:
            errors += 1
            print(f"{rel_or_msg} [COPY ERROR: {exc}]")

    print(f"\nDone. Compared {len(jobs)} file(s), copied {copied}, errors {errors}.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
