"""Lightweight stdio-to-SSE proxy for the mpy-reviewer MCP server.

Ensures only one shared MCP server process loads the embedding model,
regardless of how many Claude Code sessions are active. Each session
runs this thin proxy which bridges stdio (Claude Code) to SSE (shared server).

Must NOT import rag, torch, sentence_transformers, or any heavy dependencies.
"""

import fcntl
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

LOCK_DIR = Path.home() / ".cache" / "mpy-reviewer"

# Log to both stderr (for Claude Code's transport) and a persistent file.
# PID in the format string distinguishes concurrent proxy processes.
logging.basicConfig(
    level=logging.INFO,
    format=f"%(asctime)s - mcp-proxy[{os.getpid()}] - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

LOCK_DIR.mkdir(parents=True, exist_ok=True)
_file_handler = logging.FileHandler(LOCK_DIR / "proxy.log")
_file_handler.setFormatter(logging.Formatter(
    f"%(asctime)s - mcp-proxy[{os.getpid()}] - %(levelname)s - %(message)s"
))
logger.addHandler(_file_handler)
LOCK_FILE = LOCK_DIR / "server.lock"
HEALTH_TIMEOUT = 30  # seconds to wait for server to become healthy
HEALTH_INTERVAL = 0.5  # seconds between health checks


def _read_lock() -> dict | None:
    """Read the lock file. Returns None if missing or invalid."""
    try:
        data = json.loads(LOCK_FILE.read_text())
        if "pid" in data and "port" in data:
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return None


def _write_lock(pid: int, port: int) -> None:
    """Write the lock file."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps({
        "pid": pid,
        "port": port,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }))


def _pid_alive(pid: int) -> bool:
    """Check if a process is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _port_connectable(port: int) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def _find_free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _server_healthy(port: int) -> bool:
    """Check if the shared SSE server is healthy via TCP connect."""
    return _port_connectable(port)


def _spawn_server(port: int) -> int:
    """Spawn the shared MCP server in SSE mode as a detached process.

    Returns the PID of the spawned server.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", str(Path(__file__).parent))
    server_script = os.path.join(plugin_root, "mcp_server.py")

    # Build the command
    cmd = [
        sys.executable, server_script,
        "--transport", "sse",
        "--host", "127.0.0.1",
        "--port", str(port),
    ]

    logger.info("Spawning shared server: %s", " ".join(cmd))

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", plugin_root)

    # Log server output for diagnostics
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOCK_DIR / "server.log"
    log_file = open(log_path, "a")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=log_file,
        start_new_session=True,
        env=env,
    )
    log_file.close()  # Popen duplicates the fd

    logger.info("Server log: %s", log_path)
    return proc.pid


def _wait_for_health(port: int, timeout: float = HEALTH_TIMEOUT) -> bool:
    """Poll until the server becomes healthy or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _server_healthy(port):
            return True
        time.sleep(HEALTH_INTERVAL)
    return False


def _ensure_server() -> int:
    """Ensure a shared server is running. Returns its port.

    Uses fcntl exclusive locking to prevent concurrent proxy processes
    from spawning duplicate servers.
    """
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    spawn_lock_path = LOCK_DIR / "spawn.lock"

    fd = os.open(str(spawn_lock_path), os.O_CREAT | os.O_RDWR)
    try:
        # Block until we hold the exclusive lock
        fcntl.flock(fd, fcntl.LOCK_EX)

        # Re-check lock file under the lock — another proxy may have
        # spawned a server while we were waiting
        lock = _read_lock()
        if lock:
            pid = lock["pid"]
            port = lock["port"]
            if _pid_alive(pid) and _server_healthy(port):
                logger.info("Connecting to existing server (pid=%d, port=%d)", pid, port)
                return port
            # Stale lock
            logger.info("Stale lock (pid=%d alive=%s, port=%d healthy=%s), starting new server",
                         pid, _pid_alive(pid), port, _server_healthy(port))
            try:
                LOCK_FILE.unlink(missing_ok=True)
            except OSError:
                pass

        # Spawn a new server
        port = _find_free_port()
        pid = _spawn_server(port)
        _write_lock(pid, port)

        logger.info("Waiting for server health (pid=%d, port=%d)...", pid, port)
        if not _wait_for_health(port):
            logger.error("Server failed to start within %ds", HEALTH_TIMEOUT)
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            try:
                LOCK_FILE.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError("Shared MCP server failed to start")

        logger.info("Server healthy (pid=%d, port=%d)", pid, port)
        return port
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _watch_parent() -> None:
    """Exit if parent process dies (reparented to init/systemd)."""
    original_ppid = os.getppid()
    while True:
        time.sleep(10)
        if os.getppid() != original_ppid:
            logger.info("Parent process died (was %d), exiting", original_ppid)
            os.kill(os.getpid(), signal.SIGTERM)
            return


def _heartbeat(port: int) -> None:
    """Periodically check server health. Exit if server dies."""
    # Wait before first check to let startup settle
    time.sleep(30)
    while True:
        if not _port_connectable(port):
            logger.error("Server on port %d unreachable, exiting", port)
            os.kill(os.getpid(), signal.SIGTERM)
            return
        time.sleep(30)


def _handle_sigterm(signum, frame):
    """Clean exit on SIGTERM/SIGHUP."""
    logger.info("Received signal %d, exiting", signum)
    sys.exit(0)


def _run_proxy(port: int) -> None:
    """Run the stdio-to-SSE proxy using FastMCP's proxy support."""
    from fastmcp import FastMCP

    sse_url = f"http://127.0.0.1:{port}/sse"
    logger.info("Creating proxy to %s", sse_url)

    proxy = FastMCP.as_proxy(sse_url)
    proxy.run(transport="stdio")


def _run_direct() -> None:
    """Fallback: run the full MCP server directly in this process."""
    logger.warning("Falling back to direct stdio mode")
    from mcp_server import mcp
    mcp.run(transport="stdio")


def main():
    # Clean exit on signals
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGHUP, _handle_sigterm)

    # Exit if parent process dies
    threading.Thread(target=_watch_parent, daemon=True).start()

    try:
        port = _ensure_server()

        # Exit if the shared server becomes unreachable
        threading.Thread(target=_heartbeat, args=(port,), daemon=True).start()

        _run_proxy(port)
    except Exception as e:
        logger.error("Proxy setup failed: %s", e)
        _run_direct()


if __name__ == "__main__":
    main()
