"""Manage this loopback development service; secrets and data stay outside Git."""
import argparse
from contextlib import contextmanager
import errno
import json
import math
import os
from pathlib import Path
import secrets
import re
import shlex
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.request

REPO = Path(__file__).resolve().parents[1]


class LifecycleBusy(ValueError):
    pass


@contextmanager
def lifecycle_lock(runtime):
    """One local lifecycle command at a time; a second stop must not re-signal."""
    try:
        import fcntl
    except ImportError:
        raise ValueError("POSIX lifecycle locking required") from None
    flags = os.O_CREAT | os.O_RDWR | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(runtime / "lifecycle.lock", flags, 0o600)
    acquired = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("regular lifecycle lock required")
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                raise LifecycleBusy("local lifecycle command in progress") from None
            raise
        acquired = True
        yield
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def service_port(metadata):
    if not isinstance(metadata, dict) or not isinstance(metadata.get("url"), str):
        raise ValueError("invalid local service metadata")
    match = re.fullmatch(r"http://127\.0\.0\.1:([0-9]{4,5})", metadata["url"])
    instance = metadata.get("local_instance_id")
    if match is None or not 1024 <= int(match[1]) <= 65535 or not isinstance(instance, str) or not re.fullmatch(r"[a-f0-9]{32}", instance):
        raise ValueError("invalid local service metadata")
    return int(match[1])


def process_state(metadata, runtime):
    """Check exact launcher command ownership; zombies have already stopped."""
    port = service_port(metadata)
    pid = metadata.get("pid")
    if type(pid) is not int or not 2 <= pid <= 2147483647:
        raise ValueError("invalid local service PID")
    result = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "stat=", "-o", "command="],
                            capture_output=True, text=True, check=False)
    if result.returncode == 1:
        return "exited"
    if result.returncode != 0:
        raise ValueError("local process check unavailable")
    if not result.stdout.strip():
        return "exited"
    columns = result.stdout.strip().split(None, 1)
    state, command = columns[0], columns[1] if len(columns) == 2 else ""
    if state.startswith("Z"):
        return "exited"
    try:
        parts = shlex.split(command)
        owns = (len(parts) >= 6 and parts[1] == str(REPO / "scripts/serve.py") and
                parts[parts.index("--store") + 1] == str(runtime / "decisions.sqlite") and
                parts[parts.index("--port") + 1] == str(port))
    except (ValueError, IndexError):
        owns = False
    return "owned" if owns else "unrelated"


def wait_for_process_exit(metadata, runtime, *, timeout_s=60, probe=process_state,
                          monotonic=time.monotonic, sleep=time.sleep):
    """Drain for at most one minute. Never escalate to a forced termination."""
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or not 0 <= timeout_s <= 60:
        raise ValueError("invalid shutdown wait")
    deadline = monotonic() + timeout_s
    while True:
        state = probe(metadata, runtime)
        if state not in {"owned", "unrelated", "exited"}:
            raise ValueError("invalid local process check")
        if state != "owned":
            # A reused unrelated PID must never receive another signal.
            return True
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        sleep(min(0.05, remaining))


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
    service_port(metadata)
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
    parser.add_argument("--auto-refresh-config", type=Path)
    parser.add_argument("--no-auto-refresh", action="store_true")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        runtime = runtime_directory(args.runtime)
        with lifecycle_lock(runtime):
            _command(args, runtime)
    except LifecycleBusy:
        parser.exit(2, "A local lifecycle command is already in progress; retry after it finishes.\n")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        parser.exit(2, "Local service command failed; inspect the external runtime and port.\n")


def _command(args, runtime):
    metadata_path, key_path = runtime / "server.json", runtime / "api-key"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else None
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("invalid local service metadata")
    if args.command == "key":
        if not key_path.is_file() or key_path.is_symlink():
            raise ValueError("no local development key")
        print(key_path.read_text().strip())  # Explicit user command only; never automatic startup output.
        return
    if args.command == "status":
        try:
            if metadata is None:
                raise ValueError("not started")
            state = process_state(metadata, runtime)
            if state != "owned":
                raise ValueError("owned service not running")
            try:
                result = health(metadata)
                print(json.dumps({"running": True, "url": metadata["url"], "mode": result["mode"],
                                  "draining": bool(metadata.get("stop_requested")), "execution_enabled": False}))
            except (OSError, ValueError):
                print(json.dumps({"running": False, "process_alive": True, "url": metadata["url"],
                                  "draining": bool(metadata.get("stop_requested")), "execution_enabled": False}))
        except (OSError, ValueError):
            print(json.dumps({"running": False}))
        return
    if args.command == "stop":
        if metadata is None:
            print(json.dumps({"stopped": True, "previously_running": False}))
            return
        state = process_state(metadata, runtime)
        if state == "exited":
            metadata_path.unlink(missing_ok=True)
            print(json.dumps({"stopped": True, "previously_running": False}))
            return
        if state != "owned":
            raise ValueError("refusing to stop an unrelated process")
        if not metadata.get("stop_requested"):
            health(metadata)  # Verify this exact instance before any signal.
            metadata["stop_requested"] = True
            metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
            metadata_path.chmod(0o600)
            os.kill(metadata["pid"], signal.SIGTERM)
        if wait_for_process_exit(metadata, runtime):
            metadata_path.unlink(missing_ok=True)
            print(json.dumps({"stopped": True, "draining": False}))
        else:
            print(json.dumps({"stopped": False, "draining": True, "process_alive": True, "url": metadata["url"]}))
        return
    if not 1024 <= args.port <= 65535:
        raise ValueError("invalid port")
    if metadata:
        state = process_state(metadata, runtime)
        if state == "owned":
            if metadata.get("stop_requested"):
                print(json.dumps({"running": False, "draining": True, "process_alive": True, "startup_blocked": True}))
                return
            try:
                health(metadata)
                print(json.dumps({"running": True, "url": metadata["url"], "reused_existing_service": True}))
                return
            except (OSError, ValueError):
                print(json.dumps({"running": False, "process_alive": True, "startup_blocked": True}))
                return
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
    for option, value in (("--source-config", args.source_config), ("--collection-plan", args.collection_plan),
                          ("--auto-refresh-config", args.auto_refresh_config)):
        if value:
            command += [option, str(value.resolve())]
    if args.no_auto_refresh:
        command.append("--no-auto-refresh")
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


if __name__ == "__main__":
    main()
