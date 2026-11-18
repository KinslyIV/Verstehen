import re
from pathlib import Path

MIGRATION_NAME = re.compile(r"[0-9]{4}_.+\.sql")


def migration_files(directory: Path) -> list[Path]:
    paths = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.name != ".gitkeep"
    )
    numbers: dict[str, str] = {}
    errors = []
    for path in paths:
        if not MIGRATION_NAME.fullmatch(path.name):
            errors.append(f"{path}: use a numbered SQL migration such as 0001_name.sql")
            continue
        number = path.name[:4]
        if number in numbers:
            errors.append(
                f"renumber {path}: {number} is already used by {numbers[number]}"
            )
        else:
            numbers[number] = path.name
    if errors:
        raise ValueError("\n".join(errors))
    return paths
