import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from verstehen.app import create_app
from verstehen.config import Settings

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "app/src/lib/api/schema.d.ts"


def generate(check: bool) -> bool:
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        schema = create_app(Settings(temporary)).openapi()
        source = temporary / "openapi.json"
        output = temporary / "schema.d.ts"
        source.write_text(json.dumps(schema))
        subprocess.run(
            [
                str(ROOT / "app/node_modules/.bin/openapi-typescript"),
                str(source),
                "--output",
                str(output),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                str(ROOT / "app/node_modules/.bin/prettier"),
                "--write",
                str(output),
                "--config",
                str(ROOT / "app/prettier.config.js"),
            ],
            check=True,
            capture_output=True,
            cwd=ROOT / "app",
        )
        generated = output.read_text()
        if check:
            return TARGET.exists() and TARGET.read_text() == generated
        TARGET.write_text(generated)
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    if not generate(parser.parse_args().check):
        raise SystemExit("API types are stale; run make api-types")
