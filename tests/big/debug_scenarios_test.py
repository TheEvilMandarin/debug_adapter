"""
Integration tests for debug scenarios using the Debug Adapter Protocol (DAP).

Covers:
- Full debug session flow with server and client binaries (launch, breakpoints, inferiors).
- Attaching to an already running server process via DAP.
"""

import socket
import subprocess  # nosec B404 # noqa: S404

import pytest

from src.dap.server import DAPServer
from tests.big.conftest import BINARY_SERVER_PATH, is_ptrace_scope_allowed
from tests.big.helpers.dap import DAPClient
from tests.big.helpers.debug_orchestrator import DebugOrchestrator


@pytest.fixture
def full_flow(build_cpp_client, attached_dap_server, running_cpp_server):
    """Provide a fully initialized debug orchestrator for integration tests."""
    flow = DebugOrchestrator(build_cpp_client, attached_dap_server)
    yield flow
    flow.teardown()


@pytest.mark.skipif(
    not is_ptrace_scope_allowed(),
    reason="Test requires ptrace_scope=0 (Yama LSM setting), "
    + "but current value prevents ptrace-based debugging.",
)
def test_full_flow(full_flow: DebugOrchestrator):  # noqa: WPS213 WPS442
    """
    Lauching the server; setting a breakpoint on the function of waiting
    for a client connection and the function of displaying a message sent by the client;
    starting the client; adding a client inferior; adding a breakpoint to the client;
    finishing debugging.

    TODO: In rare cases, the first breakpoint falls on the client,
    this breakpoint gets stuck in a loop.
    """
    debug = full_flow
    # catch breakpoint on main function
    debug.wait_for_breakpoint()
    debug.set_server_breakpoints()
    debug.continue_server()
    # catch client connection function breakpoint
    debug.wait_for_breakpoint()
    debug.start_client()
    debug.add_inferior()
    debug.select_inferior()
    debug.set_client_breakpoint()
    # catch first breakpoint on server
    debug.continue_server()
    debug.wait_for_breakpoint()
    # catch second breakpoint on client
    debug.continue_server()
    debug.wait_for_breakpoint()


def assert_attach_response(response: dict):
    """Assert that the response is a successful 'attach' response."""
    assert response["type"] == "response"
    assert response["command"] == "attach"
    assert response["success"] is True


def assert_stopped_event_entry(event: dict) -> None:
    """Assert that the event is a 'stopped' event with reason 'entry'."""
    assert event["event"] == "stopped"
    assert event["body"]["reason"] == "entry"


def assert_disconnect_response(response: dict) -> None:
    """Assert that the response is a successful 'disconnect' response."""
    assert response["type"] == "response"
    assert response["command"] == "disconnect"
    assert response["success"] is True


@pytest.mark.skipif(
    not is_ptrace_scope_allowed(),
    reason="Test requires ptrace_scope=0 (Yama LSM setting), "
    + "but current value prevents ptrace-based debugging.",
)
@pytest.mark.usefixtures("running_cpp_server", "attached_dap_server")
def test_attach_to_cpp_server(attached_dap_server: DAPServer, running_cpp_server: subprocess.Popen):
    """Attach to the running C++ server using the real DAP server."""
    pid = running_cpp_server.pid
    program_path = str(BINARY_SERVER_PATH.resolve())

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(attached_dap_server.socket_path)
    client = DAPClient(sock)

    client.send_request(
        {
            "seq": 1,
            "type": "request",
            "command": "attach",
            "arguments": {"pid": pid, "program": program_path},
        },
    )

    response = client.recv_message()
    assert_attach_response(response)

    event = client.recv_message()
    assert_stopped_event_entry(event)

    client.send_request(
        {
            "seq": 2,
            "type": "request",
            "command": "disconnect",
            "arguments": {"restart": False, "terminateDebuggee": False},
        },
    )

    response = client.recv_message()
    assert_disconnect_response(response)

    client.close()
