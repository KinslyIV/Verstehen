import hashlib
import sys
from pathlib import Path

MIGRATIONS = Path("backend/src/verstehen/store/migrations")


def read_lock(lock: Path) -> dict[str, str]:
    return dict(line.split("  ", 1)[::-1] for line in lock.read_text().splitlines())


def check(root: Path, *, lock_new: bool = False) -> list[str]:
    directory = root / MIGRATIONS
    lock = directory.with_suffix(".lock")
    entries = read_lock(lock)
    errors = []
    for name, digest in entries.items():
        path = directory / name
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            errors.append(
                f"{path}: add a new numbered migration instead of editing {name}"
            )
    additions = []
    for path in sorted(directory.iterdir()):
        if path.name == ".gitkeep" or not path.is_file() or path.name in entries:
            continue
        if not path.suffix == ".sql" or not path.stem[:4].isdigit():
            errors.append(f"{path}: use a numbered SQL migration such as 0001_name.sql")
        elif lock_new:
            additions.append(
                f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            )
        else:
            errors.append(
                f"{path}: run make lock-migrations to record this new migration"
            )
    if lock_new and not errors:
        with lock.open("a") as output:
            output.writelines(additions)
    return errors


if __name__ == "__main__":
    errors = check(Path.cwd(), lock_new="--lock" in sys.argv[1:])
    print("\n".join(errors), end="\n" if errors else "")
    sys.exit(bool(errors))
