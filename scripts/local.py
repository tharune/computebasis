"""Manage this loopback development service; secrets and data stay outside Git."""
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request

REPO = Path(__file__).resolve().parents[1]


def runtime_directory(path):
    if not path.is_absolute() or path.is_symlink():
        raise ValueError("absolute external runtime directory required")
    path = path.resolve()
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise ValueError("runtime must remain outside Git")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def health(metadata):
    with urllib.request.urlopen(metadata["url"] + "/health", timeout=2) as response:
        result = json.load(response)
    if result.get("local_instance_id") != metadata.get("local_instance_id") or not metadata.get("local_instance_id"):
        raise ValueError("different service owns the port")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("start", "status", "stop", "key"))
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--source-config", type=Path)
    parser.add_argument("--collection-plan", type=Path)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        runtime = runtime_directory(args.runtime)
        metadata_path, key_path = runtime / "server.json", runtime / "api-key"
        metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else None
        if args.command == "key":
            if not key_path.is_file() or key_path.is_symlink():
                raise ValueError("no local development key")
            print(key_path.read_text().strip())  # Explicit user command only; never automatic startup output.
            return
        if args.command == "status":
            try:
                if metadata is None:
                    raise ValueError("not started")
                result = health(metadata)
                print(json.dumps({"running": True, "url": metadata["url"], "mode": result["mode"], "execution_enabled": False}))
            except (OSError, ValueError):
                print(json.dumps({"running": False}))
            return
        if args.command == "stop":
            if metadata is None:
                print(json.dumps({"stopped": True, "previously_running": False}))
                return
            health(metadata)
            process = subprocess.check_output(["ps", "-p", str(metadata["pid"]), "-o", "command="], text=True)
            if str(REPO / "scripts/serve.py") not in process or str(runtime / "decisions.sqlite") not in process:
                raise ValueError("refusing to stop an unrelated process")
            os.kill(metadata["pid"], signal.SIGTERM)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    health(metadata)
                except (OSError, ValueError):
                    metadata_path.unlink()
                    print(json.dumps({"stopped": True}))
                    return
                time.sleep(0.05)
            raise ValueError("local service did not stop")
        if not 1024 <= args.port <= 65535:
            raise ValueError("invalid port")
        if metadata:
            try:
                health(metadata)
                print(json.dumps({"running": True, "url": metadata["url"], "reused_existing_service": True}))
                return
            except (OSError, ValueError):
                pass
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", args.port))  # Do not replace an existing listener.
        if key_path.is_symlink():
            raise ValueError("refusing symlinked key")
        if not key_path.exists():
            fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as file:
                file.write(secrets.token_urlsafe(40))
        key_path.chmod(0o600)
        instance = secrets.token_hex(16)
        environment = {**os.environ, "COMPUTE_PRICING_API_KEY": key_path.read_text().strip(),
                       "COMPUTEBASIS_LOCAL_INSTANCE_ID": instance, "PYTHONDONTWRITEBYTECODE": "1"}
        command = [sys.executable, str(REPO / "scripts/serve.py"), "--store", str(runtime / "decisions.sqlite"), "--port", str(args.port)]
        for option, value in (("--source-config", args.source_config), ("--collection-plan", args.collection_plan)):
            if value:
                command += [option, str(value.resolve())]
        log_path = runtime / "server.log"
        with log_path.open("ab") as log:
            child = subprocess.Popen(command, cwd=REPO, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        log_path.chmod(0o600)
        metadata = {"pid": child.pid, "url": f"http://127.0.0.1:{args.port}", "local_instance_id": instance}
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                health(metadata)
                metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
                metadata_path.chmod(0o600)
                print(json.dumps({"running": True, "url": metadata["url"], "execution_enabled": False}))
                return
            except (OSError, ValueError):
                if child.poll() is not None:
                    break
                time.sleep(0.05)
        child.terminate()
        raise ValueError("local service did not become ready; inspect external server log")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        parser.exit(2, "Local service command failed; inspect the external runtime and port.\n")


if __name__ == "__main__":
    main()
