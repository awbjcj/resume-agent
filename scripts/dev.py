"""Run the backend and Vite frontend together on Windows, macOS, or Linux."""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def commands(
    *, api_host: str, api_port: int, web_host: str, web_port: int
) -> tuple[list[str], list[str]]:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("Required tool 'npm' was not found on PATH. Run bootstrap first.")
    backend = [
        sys.executable,
        "-m",
        "resume_agent.cli",
        "serve",
        "--host",
        api_host,
        "--port",
        str(api_port),
    ]
    frontend = [
        npm,
        "--prefix",
        "web",
        "run",
        "dev",
        "--",
        "--host",
        web_host,
        "--port",
        str(web_port),
    ]
    return backend, frontend


def _spawn(
    command: list[str], *, environment: dict[str, str] | None = None
) -> subprocess.Popen[bytes]:
    kwargs: dict[str, object] = {"cwd": ROOT, "env": environment}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]


def _stop(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def run(*, api_host: str, api_port: int, web_host: str, web_port: int) -> int:
    backend_command, frontend_command = commands(
        api_host=api_host,
        api_port=api_port,
        web_host=web_host,
        web_port=web_port,
    )
    processes: list[subprocess.Popen[bytes]] = []
    try:
        frontend_environment = os.environ.copy()
        frontend_environment["VITE_API_PROXY_TARGET"] = (
            f"http://{api_host}:{api_port}"
        )
        processes = [
            _spawn(backend_command),
            _spawn(frontend_command, environment=frontend_environment),
        ]
        print(f"Backend: http://{api_host}:{api_port}")
        print(f"Frontend: http://{web_host}:{web_port}")
        print("Press Ctrl+C to stop both processes.")
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    return code
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 130
    finally:
        for process in reversed(processes):
            _stop(process)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--web-host", default="localhost")
    parser.add_argument("--web-port", type=int, default=5173)
    args = parser.parse_args()
    raise SystemExit(
        run(
            api_host=args.api_host,
            api_port=args.api_port,
            web_host=args.web_host,
            web_port=args.web_port,
        )
    )


if __name__ == "__main__":
    main()
