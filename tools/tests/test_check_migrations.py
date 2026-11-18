from pathlib import Path

from tools.check_migrations import MIGRATIONS, check


def migration_root(tmp_path: Path) -> Path:
    directory = tmp_path / MIGRATIONS
    directory.mkdir(parents=True)
    directory.with_suffix(".lock").touch()
    return directory


def test_empty_migrations_pass(tmp_path: Path):
    migration_root(tmp_path)
    assert check(tmp_path) == []


def test_unlisted_migration_fails(tmp_path: Path):
    path = migration_root(tmp_path) / "0001_initial.sql"
    path.write_text("SELECT 1;")
    assert check(tmp_path) == [
        f"{path}: run make lock-migrations to record this new migration"
    ]


def test_edited_migration_fails(tmp_path: Path):
    path = migration_root(tmp_path) / "0001_initial.sql"
    path.write_text("SELECT 1;")
    assert check(tmp_path, lock_new=True) == []
    path.write_text("SELECT 2;")
    assert check(tmp_path) == [
        f"{path}: add a new numbered migration instead of editing {path.name}"
    ]


def test_deleted_migration_fails(tmp_path: Path):
    path = migration_root(tmp_path) / "0001_initial.sql"
    path.write_text("SELECT 1;")
    assert check(tmp_path, lock_new=True) == []
    path.unlink()
    assert check(tmp_path) == [
        f"{path}: add a new numbered migration instead of editing {path.name}"
    ]


def test_lock_only_adds_new_entries(tmp_path: Path):
    directory = migration_root(tmp_path)
    (directory / "0001_initial.sql").write_text("SELECT 1;")
    assert check(tmp_path, lock_new=True) == []
    lock = directory.with_suffix(".lock")
    original = lock.read_bytes()
    (directory / "0002_next.sql").write_text("SELECT 2;")
    assert check(tmp_path, lock_new=True) == []
    assert lock.read_bytes().startswith(original)
    assert len(lock.read_text().splitlines()) == 2
    unchanged = lock.read_bytes()
    assert check(tmp_path, lock_new=True) == []
    assert lock.read_bytes() == unchanged


def test_lock_refuses_to_rewrite_edited_entries(tmp_path: Path):
    directory = migration_root(tmp_path)
    path = directory / "0001_initial.sql"
    path.write_text("SELECT 1;")
    assert check(tmp_path, lock_new=True) == []
    lock = directory.with_suffix(".lock")
    original = lock.read_bytes()
    path.write_text("SELECT 2;")
    (directory / "0002_next.sql").write_text("SELECT 3;")
    assert check(tmp_path, lock_new=True)
    assert lock.read_bytes() == original


def test_duplicate_migration_number_fails(tmp_path: Path):
    directory = migration_root(tmp_path)
    (directory / "0002_a.sql").write_text("SELECT 1;")
    assert check(tmp_path, lock_new=True) == []
    duplicate = directory / "0002_b.sql"
    duplicate.write_text("SELECT 2;")
    original = directory.with_suffix(".lock").read_bytes()
    for lock_new in (False, True):
        assert check(tmp_path, lock_new=lock_new) == [
            f"renumber {duplicate}: 0002 is already used by 0002_a.sql"
        ]
        assert directory.with_suffix(".lock").read_bytes() == original


def test_migration_without_underscore_name_fails(tmp_path: Path):
    directory = migration_root(tmp_path)
    for name in ("0002.sql", "0002_.sql", "0002name.sql", "00022_name.sql"):
        path = directory / name
        path.write_text("SELECT 1;")
        assert check(tmp_path, lock_new=True) == [
            f"{path}: use a numbered SQL migration such as 0001_name.sql"
        ]
        assert directory.with_suffix(".lock").read_bytes() == b""
        path.unlink()
