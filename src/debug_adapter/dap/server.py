"""
DAPServer module: Server implementation for the Debug Adapter Protocol (DAP).

This module provides the server-side implementation of the Debug Adapter Protocol (DAP),
which facilitates communication between a DAP client (e.g., an IDE) and a debugger backend.
The server listens for incoming client connections, processes DAP requests, and sends
appropriate responses back to the client.

The `DAPServer` class is the core component of this module. It handles socket communication,
request processing, and response generation. It also integrates with the `DAPRequestHandler`
to delegate request handling and uses the `DAPNotifier` to send events to the client.
"""

import atexit
import json
import socket
import tempfile
from collections.abc import Iterator
from pathlib import Path

from debug_adapter.dap.notifier import DAPNotifier, NullNotifier
from debug_adapter.dap.request_handler import DAPRequestHandler

JSON_DECODE_ERROR = -32700
INTERNAL_JSON_RPC_ERROR = -32603


class DAPServer:
    """Class for processing client requests via Debug Adapter Protocol (DAP)."""

    def __init__(self, request_handler: DAPRequestHandler):
        """Server initialization."""
        self._request_handler = request_handler
        self._server_socket = None
        self.client_conn = None
        self.notifier = NullNotifier()
        self._temp_dir = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self._socket_path = str(Path(self._temp_dir.name) / "dap_socket")
        self._buffer = b""
        atexit.register(self.stop)

    @property
    def socket_path(self) -> str:
        """Path to the Unix domain socket used by the server."""
        return self._socket_path

    def start(self):
        """Start the server and waits for the client to connect."""
        self._server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_socket.bind(self._socket_path)
        self._server_socket.listen(1)
        print(f"SOCKET_PATH={self._socket_path}", flush=True)

        self.client_conn = self._server_socket.accept()[0]
        print("Client connected via Unix socket")

        self.notifier = DAPNotifier(self)
        self._request_handler.notifier = self.notifier

    def stop(self):
        """Stop the server."""
        if self._server_socket:
            self._server_socket.close()
            print("Server stopped.")  # TODO: change print to logging for filtering
        if self.client_conn:
            self.client_conn.close()
        self._temp_dir.cleanup()

    def handle_requests(self):
        """Process client requests and send responses."""
        while True:
            request = self._receive_request()
            if request is None:
                break

            try:
                responses = self._request_handler.handle_request(request)
                for response in responses:
                    self._send_response(response)
            except (KeyError, ValueError, TypeError, RuntimeError) as err:
                self._send_error_response(f"Internal error: {err}", INTERNAL_JSON_RPC_ERROR)

    def _send_response(self, response: Iterator[dict] | dict):
        """
        Send a JSON response to the client over a socket.

        :param response: JSON response or event object.
        """
        response_str = json.dumps(response)
        content_length = len(response_str.encode())
        header = f"Content-Length: {content_length}\r\n\r\n"
        if self.client_conn:
            self.client_conn.sendall((header + response_str).encode())

    def _send_error_response(self, message: str, code: int):
        """
        Send an error response to the client.

        :param message: Error message.
        :param code: JSON-RPC error code.
        """
        error_response = {
            "jsonrpc": "2.0",
            "error": {
                "code": code,
                "message": message,
            },
        }
        self._send_response(error_response)

    def _receive_request(self) -> dict | None:
        """
        Read data from the socket, accumulates it in self._buffer
        and extracts a single complete JSON request if possible.
        """
        while True:
            # Trying to extract the full query from the current buffer
            request, buffer = self._extract_request_from_buffer(self._buffer)
            self._buffer = buffer

            if request is not None:
                return request

            # If there is no request, read new data from the socket
            data = self._receive_data()
            if not data:
                # If no data is received, terminate reading.
                return None
            self._buffer += data

    def _extract_request_from_buffer(self, buffer: bytes) -> tuple[dict | None, bytes]:
        """
        Attempt to extract the full JSON request from the buffer.
        Returns a tuple (request, remaining_buffer), where request is the extracted request
        (or None if the request could not be extracted) and remaining_buffer is the remaining data.
        """
        http_header_end_marker = b"\r\n\r\n"
        header_end_marker_length = len(http_header_end_marker)
        header_end = buffer.find(http_header_end_marker)
        if header_end == -1:
            # The headings are not complete.
            return None, buffer

        headers = buffer[:header_end].decode()
        content_length = _get_content_length(headers)
        if content_length is None:
            # Content-Length header not found
            return None, buffer

        total_length = header_end + header_end_marker_length + content_length
        if len(buffer) < total_length:
            # The request body has not yet been fully received.
            return None, buffer

        request_body = buffer[header_end + header_end_marker_length : total_length]
        try:
            request = json.loads(request_body.decode())
        except json.JSONDecodeError as err:
            self._send_error_response(f"Invalid JSON format: {err}", JSON_DECODE_ERROR)
            return None, buffer[total_length:]
        remaining_buffer = buffer[total_length:]
        return request, remaining_buffer

    def _receive_data(self) -> bytes | None:
        """
        Receive data from the client connection.

        :return: Received data or None if no connection or no data.
        """
        if self.client_conn:
            return self.client_conn.recv(1024)
        return None

    def _process_buffer(self, buffer: bytes) -> dict | None:
        """
        Process the buffer to extract a complete JSON request.

        :param buffer: The data buffer.
        :return: A parsed JSON request as a dictionary or None if the request is incomplete.
        """
        if b"\r\n\r\n" not in buffer:
            return None

        headers, _, body = buffer.partition(b"\r\n\r\n")
        content_length = _get_content_length(headers.decode())
        if content_length is not None and len(body) >= content_length:
            request_body = body[:content_length]
            return json.loads(request_body.decode())

        return None


def _get_content_length(headers: str) -> int | None:
    """
    Retrieve the Content-Length value from the headers.

    :param headers: Request headers as a string.
    :return: Content-Length value or None if there is no header.
    """
    for header in headers.split("\r\n"):
        if header.lower().startswith("content-length:"):
            return int(header.split(":")[1].strip())
    return None
