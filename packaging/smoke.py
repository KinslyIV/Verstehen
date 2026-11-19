import json
import os
import secrets
import selectors
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def smoke(binary: Path) -> None:
    subprocess.run([binary, "--self-check"], check=True, timeout=60)
    with tempfile.TemporaryDirectory(prefix="verstehen-smoke-") as directory:
        env = {k: v for k, v in os.environ.items() if not k.startswith("VERSTEHEN_")}
        token = secrets.token_hex(32)
        env.update(
            VERSTEHEN_DATA_DIR=directory, VERSTEHEN_DESKTOP="1", VERSTEHEN_TOKEN=token
        )
        with subprocess.Popen(
            [binary], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE
        ) as process:
            try:
                assert process.stdout is not None
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    assert selector.select(timeout=30), (
                        "No port handshake within 30 seconds"
                    )
                line = process.stdout.readline()
                port = json.loads(line)["port"]
                print(line.decode().strip())
                url = f"http://127.0.0.1:{port}/api/health"
                with urlopen(
                    Request(url, headers={"x-verstehen-token": token}), timeout=5
                ) as response:
                    assert response.status == 200
                    assert json.load(response) == {"status": "ok"}
                try:
                    urlopen(url, timeout=5)
                except HTTPError as error:
                    assert error.code == 403
                else:
                    raise AssertionError("Unauthenticated health was not refused")
                assert process.stdin is not None
                process.stdin.close()
                assert process.wait(timeout=10) == 0
                assert (Path(directory) / "verstehen.db").exists()
                assert b"" == process.stdout.read()
                print(
                    "health with token: 200; without token: 403; stdin EOF: exit 0; migrations: OK"
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    smoke(Path(sys.argv[1]).resolve())
