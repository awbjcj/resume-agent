from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script(name: str):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_seeds_examples_without_overwriting_local_files(tmp_path):
    bootstrap = _load_script("bootstrap")
    (tmp_path / "config").mkdir()
    (tmp_path / ".env.example").write_text("KEY=example\n", encoding="utf-8")
    (tmp_path / "config" / "search.yaml.example").write_text(
        "titles: []\n", encoding="utf-8"
    )
    existing = tmp_path / "config" / "review.yaml"
    existing.write_text("max_rounds: 9\n", encoding="utf-8")
    (tmp_path / "config" / "review.yaml.example").write_text(
        "max_rounds: 2\n", encoding="utf-8"
    )

    created = bootstrap.seed_local_config(tmp_path)

    assert {path.relative_to(tmp_path).as_posix() for path in created} == {
        ".env",
        "config/search.yaml",
    }
    assert existing.read_text(encoding="utf-8") == "max_rounds: 9\n"


def test_dev_commands_use_current_python_and_standard_npm_script(monkeypatch):
    dev = _load_script("dev")
    monkeypatch.setattr(dev.shutil, "which", lambda name: "/tools/npm")

    backend, frontend = dev.commands(
        api_host="127.0.0.1", api_port=8100, web_host="localhost", web_port=3100
    )

    assert backend[:4] == [dev.sys.executable, "-m", "resume_agent.cli", "serve"]
    assert backend[-4:] == ["--host", "127.0.0.1", "--port", "8100"]
    assert frontend == [
        "/tools/npm",
        "--prefix",
        "web",
        "run",
        "dev",
        "--",
        "--host",
        "localhost",
        "--port",
        "3100",
    ]


def test_dev_passes_selected_api_port_to_vite_proxy(monkeypatch):
    dev = _load_script("dev")
    monkeypatch.setattr(
        dev,
        "commands",
        lambda **kwargs: (["backend"], ["frontend"]),
    )
    environments = []

    class FinishedProcess:
        def __init__(self, code):
            self.code = code

        def poll(self):
            return self.code

    def fake_spawn(command, *, environment=None):
        environments.append(environment)
        return FinishedProcess(0 if command == ["backend"] else None)

    monkeypatch.setattr(dev, "_spawn", fake_spawn)
    monkeypatch.setattr(dev, "_stop", lambda process: None)

    assert dev.run(
        api_host="127.0.0.1", api_port=8123, web_host="localhost", web_port=5179
    ) == 0
    assert environments[0] is None
    assert environments[1]["VITE_API_PROXY_TARGET"] == "http://127.0.0.1:8123"
