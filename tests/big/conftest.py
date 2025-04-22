"""Pytest configuration and fixtures for integration testing of the DAP server and backend."""

import subprocess  # nosec B404 # noqa: S404
import threading
import time
from collections.abc import Generator
from pathlib import Path

import pytest

from src.dap.request_handler import DAPRequestHandler
from src.dap.server import DAPServer  # noqa: WPS450
from src.gdb.backend import GDBBackend

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
CPP_SERVER_SOURCE = ARTIFACTS_DIR / "server.cpp"
CPP_CLIENT_SOURCE = ARTIFACTS_DIR / "client.cpp"
BINARY_SERVER_PATH = ARTIFACTS_DIR / "server_debug"
BINARY_CLIENT_PATH = ARTIFACTS_DIR / "client_debug"
GDB_PATH = "/usr/bin/gdb"


def is_ptrace_scope_allowed() -> bool:
    """
    Return True if /proc/sys/kernel/yama/ptrace_scope is 0,
    meaning the system allows ptrace of non-child processes
    (required for debugging-related tests).
    """
    ptrace_path = Path("/proc/sys/kernel/yama/ptrace_scope")
    if not ptrace_path.exists():
        return True

    with ptrace_path.open("r") as file:
        return file.read().strip() == "0"


@pytest.fixture(scope="session")
def build_cpp_server() -> Generator[Path, None, None]:
    """Compile the server.cpp file in debug mode."""
    compile_cmd = ["g++", "-g", "-O0", "-o", str(BINARY_SERVER_PATH), str(CPP_SERVER_SOURCE)]
    subprocess.run(compile_cmd, check=True)  # nosec B603 # noqa: S603
    yield BINARY_SERVER_PATH
    if BINARY_SERVER_PATH.exists():
        BINARY_SERVER_PATH.unlink()


@pytest.fixture()
def running_cpp_server(
    build_cpp_server: Path,  # noqa: WPS442
) -> Generator[subprocess.Popen, None, None]:
    """Run the compiled server binary in the background."""
    proc = subprocess.Popen([str(build_cpp_server)])  # nosec B603 # noqa: S603
    yield proc
    proc.terminate()
    proc.wait()


@pytest.fixture(scope="session")
def build_cpp_client() -> Generator[Path, None, None]:
    """Compile the client.cpp file in debug mode."""
    compile_cmd = ["g++", "-g", "-O0", "-o", str(BINARY_CLIENT_PATH), str(CPP_CLIENT_SOURCE)]
    subprocess.run(compile_cmd, check=True)  # nosec B603 # noqa: S603
    yield BINARY_CLIENT_PATH
    if BINARY_CLIENT_PATH.exists():
        BINARY_CLIENT_PATH.unlink()


def _start_dap_server(gdb_backend: GDBBackend) -> tuple[DAPServer, threading.Thread]:
    request_handler = DAPRequestHandler(gdb_backend)
    server = DAPServer(request_handler)

    def server_thread():  # noqa: WPS430
        try:
            server.start()
            server.handle_requests()
        except OSError as err:
            print(f"Server thread stopped: {err}")

    thread = threading.Thread(target=server_thread, daemon=True)
    thread.start()
    return server, thread


@pytest.fixture()
def attached_dap_server() -> Generator[DAPServer, None, None]:
    """Start the DAP server using real GDBBackend and DAPRequestHandler."""
    gdb_backend = GDBBackend(gdb_path=GDB_PATH)
    gdb_backend.start()

    server, thread = _start_dap_server(gdb_backend)

    socket_path = Path(server.socket_path)
    timeout = 5
    interval = 0.1
    for _ in range(int(timeout / interval)):
        if socket_path.exists():
            break
        time.sleep(interval)
    else:
        pytest.fail("DAP server socket did not appear in time")

    yield server

    server.stop()
    gdb_backend.stop()
    thread.join(timeout=1)
