import re
from pathlib import Path, PurePosixPath
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
spa = root.parent / "app" / "build"
binaries = []
datas = collect_data_files(
    "verstehen", includes=["store/migrations/*.sql", "teaching/prompts/**/*.md"]
)
datas += [(str(spa), "spa"), (str(root.parent / "packaging" / "icons"), "icons")]
datas += copy_metadata("verstehen", recursive=True)
hiddenimports = collect_submodules("uvicorn") + ["pydantic_ai.mcp"]
for package in (
    "asyncssh",
    "cryptography",
    "claude_agent_sdk",
    "fastmcp",
    "mcp",
    "pypdfium2",
    "pypdfium2_raw",
    "resvg_py",
):
    data, binary, hidden = collect_all(package)
    datas += [entry for entry in data if not entry[0].endswith("_bundled/claude")]
    binaries += [entry for entry in binary if not entry[0].endswith("_bundled/claude")]
    hiddenimports += hidden

UNUSED_QT_LIBRARY = re.compile(
    r"libQt6(3D|Charts|Concurrent|DataVisualization|Graphs|Labs|Location|Multimedia|OpenGLWidgets"
    r"|PositioningQuick|Qml(Core|DesignSupport|LocalStorage|Network|XmlListModel)|Quick3D(?!Utils)"
    r"|QuickControls2|QuickDialogs2|QuickEffects|QuickLayouts|QuickParticles|QuickShapes"
    r"|QuickTemplates2|QuickTest|QuickTimeline|QuickVectorImage|RemoteObjects|Scxml|Sensors"
    r"|ShaderTools|SpatialAudio|Sql|StateMachine|Test|TextToSpeech|VirtualKeyboardSettings"
    r"|WaylandCompositor|WebChannelQuick|WebEngineQuick|WebSockets|WebView)\w*\.so"
)
KEPT_LANGUAGES = {"en", "de"}


def shipped(destination: str) -> bool:
    """Drop Qt parts nothing in the app loads: unused libraries, QML, its debugger, other languages."""
    path = PurePosixPath(destination)
    qt = path.parts[2:] if path.parts[:2] == ("PySide6", "Qt") else ()
    if qt[:1] == ("qml",) or qt[:2] == ("plugins", "qmltooling"):
        return False
    in_qt_lib = qt[:1] == ("lib",) or len(path.parts) == 1
    if in_qt_lib and UNUSED_QT_LIBRARY.match(path.name):
        return False
    if qt[:1] == ("translations",) and path.suffix in (".qm", ".pak"):
        locale = path.stem.rsplit("_", 1)[-1] if path.suffix == ".qm" else path.stem
        return locale.split("-")[0] in KEPT_LANGUAGES
    return True


a = Analysis([str(root / "packaging/entrypoint.py")], pathex=[str(root / "src")],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["playwright"])
a.binaries = [entry for entry in a.binaries if shipped(entry[0])]
a.datas = [entry for entry in a.datas if shipped(entry[0])]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="verstehen", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="verstehen")
