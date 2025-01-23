import json
import socket
from collections.abc import Iterator

from dap.request_handler import DAPRequestHandler

JSON_DECODE_ERROR = -32700
INTERNAL_JSON_RPC_ERROR = -32603


class DAPServer:
    """Class for processing client requests via Debug Adapter Protocol (DAP)."""

    def __init__(self, host: str, port: int, request_handler: DAPRequestHandler):
        """Server initialization."""
        self.host = host
        self.port = port
        self.request_handler = request_handler
        self.server_socket = None
        self.client_conn = None

    def start(self):
        """Start the server and waits for the client to connect."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(1)
        print(f"DAP server is listening on {self.host}:{self.port}", flush=True)

        client_conn, client_address = self.server_socket.accept()
        self.client_conn = client_conn
        self.client_address = client_address

        print(f"Client connected: {client_address}")

    def handle_requests(self):
        """Process client requests and sends responses."""
        while True:
            request = self._receive_request()
            if request is None:
                break

            for response in self.request_handler.handle_request(request):
                self._send_response(response)

    def stop(self):
        """Stop the server."""
        if self.server_socket:
            self.server_socket.close()
            print("Server stopped.")  # TODO: change print to logging for filtering

    def _process_request(self, request_body: bytes):
        """
        Process a client request.

        :param request_body: JSON request body.
        """
        try:
            request = json.loads(request_body.decode())
            print(f"Received request: {request}")

            response = self.request_handler.handle_request(request)
            if response:
                self._send_response(response)

        except json.JSONDecodeError:
            self._send_error_response("Invalid JSON format", code=JSON_DECODE_ERROR)
        except Exception as err:
            self._send_error_response(str(err), code=INTERNAL_JSON_RPC_ERROR)

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
            print(f"Sent response: {response}", flush=True)

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
        Accept a request from a client.

        :return: JSON request as a dictionary or None if no data is received.
        """
        buffer = b""
        while True:
            data = self._receive_data()
            if not data:
                return None

            buffer += data

            request = self._process_buffer(buffer)
            if request is not None:
                return request

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
