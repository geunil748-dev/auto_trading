from __future__ import annotations

import argparse
import importlib.metadata
import importlib.util
import json
import socket
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only startup preflight checks.")
    parser.add_argument("--monitor-port", type=int, default=4174)
    parser.add_argument("--fail-used-port", action="store_true")
    args = parser.parse_args()

    payload = run_checks(
        monitor_port=args.monitor_port,
        fail_used_port=args.fail_used_port,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    raise SystemExit(0 if payload["status"] == "PASS" else 1)


def run_checks(
    monitor_port: int = 4174,
    fail_used_port: bool = False,
) -> dict[str, Any]:
    checks = [
        _check_path("project_root", ROOT, ROOT.exists(), "Run from an existing checkout."),
        _check_path("monitor_settings", ROOT / "monitor" / "trading_settings.json"),
        _check_path("pyproject", ROOT / "pyproject.toml"),
        _check_dependency_file(),
        _check_module("pythonnet", package="pythonnet"),
        _check_import("clr"),
        _check_db_modules(),
        _check_writable_dir(
            "logs_dir",
            ROOT / "logs",
            pass_when_missing=True,
            missing_note="startup scripts create this directory if it is missing",
        ),
        _check_writable_dir("state_dir", ROOT / "monitor"),
        _check_port(
            f"port_{monitor_port}",
            "127.0.0.1",
            monitor_port,
            fail_when_in_use=fail_used_port,
        ),
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


def _check_writable_dir(
    name: str,
    path: Path,
    pass_when_missing: bool = False,
    missing_note: str | None = None,
) -> dict[str, Any]:
    return _check_runtime_dir(
        name,
        path,
        pass_when_missing=pass_when_missing,
        missing_note=missing_note,
    )


def _check_runtime_dir(
    name: str,
    path: Path,
    pass_when_missing: bool = False,
    missing_note: str | None = None,
) -> dict[str, Any]:
    if not path.exists():
        return {
            "name": name,
            "status": "PASS" if pass_when_missing else "FAIL",
            "path": str(path),
            "exists": False,
            "note": missing_note,
            "remedy": None if pass_when_missing else "Create the directory before startup.",
        }
    return {
        "name": name,
        "status": "PASS" if path.is_dir() else "FAIL",
        "path": str(path),
        "exists": True,
        "remedy": None if path.is_dir() else "Path must be a directory.",
    }


def _check_port(
    name: str,
    host: str,
    port: int,
    fail_when_in_use: bool = False,
) -> dict[str, Any]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        in_use = sock.connect_ex((host, port)) == 0
    failed = in_use and fail_when_in_use
    return {
        "name": name,
        "status": "FAIL" if failed else "PASS",
        "host": host,
        "port": port,
        "in_use": in_use,
        "note": "read-only check; use --fail-used-port for startup gating",
        "remedy": "Stop the existing listener before starting monitor." if failed else None,
    }


def _safe_error(exc: Exception) -> str:
    return (str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__)[:300]


if __name__ == "__main__":
    main()
