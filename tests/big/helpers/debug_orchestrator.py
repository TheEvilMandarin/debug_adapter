"""
High-level orchestration of full debug sessions via DAP.

Provides:
DebugOrchestrator: a test utility that controls end-to-end debug scenarios,
including launching the debuggee, managing breakpoints, and attaching client processes.
"""

import socket
import subprocess  # noqa: S404 # nosec B404
from pathlib import Path

from src.dap.server import DAPServer
from tests.big.conftest import BINARY_SERVER_PATH, CPP_CLIENT_SOURCE, CPP_SERVER_SOURCE
from tests.big.helpers.dap import DAPClient, recv_until_event


class DebugOrchestrator:  # noqa: WPS230
    """Class that manages a full debug session via DAP for testing purposes."""

    def __init__(self, build_cpp_client: Path, attached_dap_server: DAPServer):  # noqa: WPS442
        """Initialize the debug session and send initial launch request."""
        self.client_bin_path = str(build_cpp_client.resolve())
        self.attached_dap_server = attached_dap_server
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.attached_dap_server.socket_path)
        self.dap = DAPClient(self.sock)

        self.proc = None
        self.pid = None
        self.seq = 1

        self.dap.send_request(
            {
                "seq": self.seq,
                "type": "request",
                "command": "launch",
                "arguments": {"program": str(BINARY_SERVER_PATH.resolve()), "args": []},
            },
        )
        self.seq += 1

    def teardown(self):
        """Disconnect from the DAP session and clean up the process."""
        self._disconnect_dap()
        self._close_resources()
        self._terminate_client_process()

    def _disconnect_dap(self):
        """Send disconnect request to the DAP server."""
        try:
            self.dap.send_request(
                {
                    "seq": self.seq,
                    "type": "request",
                    "command": "disconnect",
                    "arguments": {"restart": False, "terminateDebuggee": True},
                },
            )
            response = self.dap.recv_message()
            assert response["command"] == "disconnect"
        except Exception as err:
            print("Error during disconnect:", err)

    def _close_resources(self):
        """Close DAP and socket connections."""
        self.dap.close()
        self.sock.close()

    def _terminate_client_process(self):
        """Terminate the client subprocess, if any."""
        if self.proc:
            if self.proc.stdin and not self.proc.stdin.closed:
                self.proc.stdin.close()
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()

    def next_seq(self):
        """Return the next sequence number for DAP requests."""
        self.seq += 1
        return self.seq

    def set_server_breakpoints(self):
        """Set a breakpoint in the server source file."""
        self.dap.send_request(
            {
                "seq": self.next_seq(),
                "type": "request",
                "command": "setBreakpoints",
                "arguments": {
                    "source": {"path": str(CPP_SERVER_SOURCE)},
                    "breakpoints": [{"line": 39}, {"line": 55}],
                },
            },
        )
        assert self.dap.recv_message()["success"]

    def continue_server(self):
        """Send the 'continue' command for the server thread."""
        self.dap.send_request(
            {
                "seq": self.next_seq(),
                "type": "request",
                "command": "continue",
                "arguments": {"threadId": 1},
            },
        )
        recv_until_event(self.dap, "continued")

    def start_client(self):
        """Start the client binary as a subprocess."""
        self.proc = subprocess.Popen([self.client_bin_path], text=True)  # nosec B603 # noqa: S603
        self.pid = self.proc.pid
        assert self.pid is not None

    def wait_for_breakpoint(self):
        """Wait for the server to hit the next breakpoint."""
        recv_until_event(self.dap, "stopped", reason="breakpoint-hit")

    def add_inferior(self):
        """Add inferior process by PID."""
        self.dap.send_request(
            {
                "seq": self.next_seq(),
                "type": "request",
                "command": "addInferiors",
                "arguments": {"pids": [self.pid]},
            },
        )
        response = self.dap.recv_message()
        assert response["success"]

    def select_inferior(self):
        """Select a new inferior process by PID."""
        self.dap.send_request(
            {
                "seq": self.next_seq(),
                "type": "request",
                "command": "selectInferior",
                "arguments": {"pid": self.pid},
            },
        )
        assert self.dap.recv_message()["success"]

    def set_client_breakpoint(self):
        """Set a breakpoint in the client source file."""
        self.dap.send_request(
            {
                "seq": self.next_seq(),
                "type": "request",
                "command": "setBreakpoints",
                "arguments": {
                    "source": {"path": str(CPP_CLIENT_SOURCE)},
                    "breakpoints": [{"line": 44}],
                },
            },
        )
        assert self.dap.recv_message()["success"]
