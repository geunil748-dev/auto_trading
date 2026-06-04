from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import socket
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    payload = run_checks()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(0 if payload["status"] == "PASS" else 1)


def run_checks() -> dict[str, Any]:
    checks = [
        _check_path("project_root", ROOT, ROOT.exists(), "Run from an existing checkout."),
        _check_path("monitor_settings", ROOT / "monitor" / "trading_settings.json"),
        _check_path("pyproject", ROOT / "pyproject.toml"),
        _check_dependency_file(),
        _check_module("pythonnet", package="pythonnet"),
        _check_import("clr"),
        _check_db_modules(),
        _check_writable_dir("logs_dir", ROOT / "logs"),
        _check_writable_dir("state_dir", ROOT / "monitor"),
        _check_port("port_4174", "127.0.0.1", 4174),
    ]
    failed = [item for item in checks if item["status"] != "PASS"]
    return {
        "status": "PASS" if not failed else "FAIL",
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "project_root": str(ROOT),
        "checks": checks,
        "failed": failed,
    }


def _check_path(
    name: str,
    path: Path,
    exists: bool | None = None,
    remedy: str = "Restore the missing file before startup.",
) -> dict[str, Any]:
    found = path.exists() if exists is None else exists
    return {
        "name": name,
        "status": "PASS" if found else "FAIL",
        "path": str(path),
        "remedy": None if found else remedy,
    }


def _check_dependency_file() -> dict[str, Any]:
    files = [
        ROOT / "requirements.txt",
        ROOT / "pyproject.toml",
        ROOT / "setup.cfg",
        ROOT / "environment.yml",
    ]
    existing = [str(path) for path in files if path.exists()]
    return {
        "name": "dependency_file",
        "status": "PASS" if existing else "FAIL",
        "files": existing,
        "remedy": None if existing else "Add pyproject.toml or requirements.txt.",
    }


def _check_module(name: str, package: str | None = None) -> dict[str, Any]:
    package_name = package or name
    try:
        version = importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        version = None
    spec = importlib.util.find_spec(name)
    ok = version is not None or spec is not None
    return {
        "name": f"{name}_installed",
        "status": "PASS" if ok else "FAIL",
        "version": version,
        "remedy": None if ok else f"Install {package_name} in the startup Python environment.",
    }


def _check_import(name: str) -> dict[str, Any]:
    try:
        __import__(name)
    except Exception as exc:
        return {
            "name": f"import_{name}",
            "status": "FAIL",
            "error": _safe_error(exc),
            "remedy": f"Install or repair the package that provides {name}.",
        }
    return {"name": f"import_{name}", "status": "PASS", "error": None, "remedy": None}


def _check_db_modules() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "src"))
    try:
        import trading_bot.database  # noqa: F401
    except Exception as exc:
        return {
            "name": "db_modules_import",
            "status": "FAIL",
            "error": _safe_error(exc),
            "remedy": "Install DB dependencies in the startup Python environment.",
        }
    return {"name": "db_modules_import", "status": "PASS", "error": None, "remedy": None}


def _check_writable_dir(name: str, path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "name": name,
            "status": "FAIL",
            "path": str(path),
            "remedy": "Create the directory before startup.",
        }
    return {
        "name": name,
        "status": "PASS" if path.is_dir() else "FAIL",
        "path": str(path),
        "remedy": None if path.is_dir() else "Path must be a directory.",
    }


def _check_port(name: str, host: str, port: int) -> dict[str, Any]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        in_use = sock.connect_ex((host, port)) == 0
    return {
        "name": name,
        "status": "PASS",
        "host": host,
        "port": port,
        "in_use": in_use,
        "note": "read-only check",
    }


def _safe_error(exc: Exception) -> str:
    return (str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__)[:300]


if __name__ == "__main__":
    main()
