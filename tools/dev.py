import os
import signal
import subprocess
import tempfile
import time


def main() -> None:
    """Run the browser sidecar and Vite with temporary data, stopping both on exit."""
    children: list[subprocess.Popen] = []
    stopping = False

    def stop(signum: int, frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    with tempfile.TemporaryDirectory(prefix="verstehen-dev-") as directory:
        env = os.environ.copy()
        env["VERSTEHEN_DATA_DIR"] = directory
        env["VERSTEHEN_PORT"] = env.get("VERSTEHEN_PORT", "8765")
        try:
            for command in (
                ["uv", "run", "--project", "backend", "verstehen"],
                ["npm", "run", "dev", "--prefix", "app", "--", "--strictPort"],
            ):
                children.append(
                    subprocess.Popen(command, env=env, start_new_session=True)
                )
            while not stopping and all(child.poll() is None for child in children):
                time.sleep(0.1)
        finally:
            for child in children:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGTERM)
            for child in children:
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
        if not stopping and any(child.returncode for child in children):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
