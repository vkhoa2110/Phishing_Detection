"""Preview or remove regenerable project caches, without entering asset folders."""
import argparse
import os
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[2]
CACHE_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDED = {".git", ".venv", "venv", "node_modules", "models", "data", "artifacts"}


def cache_directories(root):
    for parent, directories, files in os.walk(root, followlinks=False):
        if "pyvenv.cfg" in files:
            directories.clear()
            continue
        descend = []
        for name in sorted(directories):
            path = Path(parent) / name
            if path.is_symlink() or name in EXCLUDED:
                continue
            if name in CACHE_NAMES:
                yield path
            else:
                descend.append(name)
        directories[:] = descend


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Delete the listed caches; default is preview only.")
    args = parser.parse_args(argv)
    paths = list(cache_directories(ROOT))
    total_files, total_bytes = 0, 0
    for path in paths:
        files = [p for p in path.rglob("*") if p.is_file() and not p.is_symlink()]
        total_files += len(files)
        total_bytes += sum(p.stat().st_size for p in files)
        print(f"{'Remove' if args.apply else 'Would remove'} {path.relative_to(ROOT)}/")
        if args.apply:
            shutil.rmtree(path)
    print(f"{'Removed' if args.apply else 'Preview'}: {len(paths)} cache directories, "
          f"{total_files} files, {total_bytes / 1048576:.2f} MiB.")
    if paths and not args.apply:
        print("Run with --apply or use make clean to remove these caches.")


if __name__ == "__main__":
    main()
