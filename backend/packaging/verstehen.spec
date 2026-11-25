from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
spa = root.parent / "app" / "build"
binaries = []
datas = collect_data_files(
    "verstehen", includes=["store/migrations/*.sql", "teaching/prompts/**/*.md"]
)
datas += [(str(spa), "spa")]
datas += copy_metadata("verstehen", recursive=True)
hiddenimports = collect_submodules("uvicorn")
for package in (
    "asyncssh",
    "cryptography",
    "playwright",
    "claude_agent_sdk",
    "pypdfium2",
    "pypdfium2_raw",
    "resvg_py",
):
    data, binary, hidden = collect_all(package)
    datas += [entry for entry in data if not entry[0].endswith("_bundled/claude")]
    binaries += [entry for entry in binary if not entry[0].endswith("_bundled/claude")]
    hiddenimports += hidden

a = Analysis([str(root / "packaging/entrypoint.py")], pathex=[str(root / "src")],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports)
a.datas = [entry for entry in a.datas if not entry[0].startswith("playwright/driver/")]
a.binaries = [entry for entry in a.binaries if not entry[0].startswith("playwright/driver/")]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="verstehen", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="verstehen")
