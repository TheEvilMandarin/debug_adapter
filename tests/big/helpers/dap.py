"""
Helper module for low-level interaction with the Debug Adapter Protocol (DAP).

Contains:
- DAPClient: a minimal DAP client for sending requests and receiving responses.
- recv_until_event: utility to wait for specific DAP events.
- Internal logic for parsing DAP messages from raw socket buffers.
"""

import json
import socket
import time

import pytest

from src.dap.server import _get_content_length  # noqa: WPS450


class DAPClient:
    """A simple Debug Adapter Protocol (DAP) client for testing."""

    def __init__(self, sock: socket.socket) -> None:
        """Initialize the client with a connected socket."""
        self.sock = sock
        self.buffer = b""
        self.closed = False

    def send_request(self, request: dict) -> None:
        """
        Send a DAP request to the server.

        :param request: A dictionary representing the DAP request.
        """
        if self.closed:
            pytest.fail("Attempt to send on closed client")
        body = json.dumps(request)
        content_length = len(body.encode())
        header = f"Content-Length: {content_length}\r\n\r\n"
        self.sock.sendall((header + body).encode())

    def recv_message(self, allow_disconnect: bool = False) -> dict:
        """
        Receive a DAP message from the server.

        :return: Parsed JSON response as a dictionary.
        """
        while True:
            extracted = _extract_response_from_buffer(self.buffer)
            response = extracted[0]
            self.buffer = extracted[1]
            if response is not None:
                return response
            chunk = self.sock.recv(1024)
            if not chunk:
                if allow_disconnect:
                    return {}
                pytest.fail("Connection closed unexpectedly")
            self.buffer += chunk

    def close(self) -> None:
        """Close the client socket."""
        if not self.closed:
            self.sock.close()
            self.closed = True


def _extract_response_from_buffer(buffer: bytes) -> tuple[dict | None, bytes]:
    marker = b"\r\n\r\n"
    header_end = buffer.find(marker)
    if header_end == -1:
        return None, buffer

    headers = buffer[:header_end].decode(errors="replace")
    content_length = _get_content_length(headers)
    if content_length is None:
        pytest.fail("Missing Content-Length header")

    total_length = header_end + len(marker) + content_length
    if len(buffer) < total_length:
        return None, buffer

    body = buffer[header_end + len(marker) : total_length]
    try:
        response = json.loads(body.decode(errors="replace"))
    except json.JSONDecodeError as err:
        pytest.fail(f"Failed to decode JSON: {err}")

    remaining = buffer[total_length:]
    return response, remaining


def recv_until_event(
    client: DAPClient,
    expected_event: str,
    reason: str | None = None,
    timeout: float = 5.0,
):
    """Wait for a specific DAP event message from the server."""
    start = time.time()
    while time.time() - start < timeout:
        msg = client.recv_message()

        event_type = msg.get("type")
        event_name = msg.get("event")
        event_body = msg.get("body", {})
        event_reason = event_body.get("reason")

        is_expected_event = event_type == "event" and event_name == expected_event
        reason_matches = reason is None or event_reason == reason

        if is_expected_event and reason_matches:
            return msg
    pytest.fail(f"Timeout waiting for event '{expected_event}' with reason='{reason}'")
