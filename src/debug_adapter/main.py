"""Entry point for the Debug Adapter Protocol (DAP) server."""

import argparse

from debug_adapter.dap.request_handler import DAPRequestHandler
from debug_adapter.dap.server import DAPServer
from debug_adapter.gdb.backend import GDBBackend


def _setup_components(gdb_path: str) -> tuple[GDBBackend, DAPRequestHandler, DAPServer]:
    """Initialize and return all required components."""
    gdb_backend = GDBBackend(gdb_path=gdb_path)
    request_handler = DAPRequestHandler(gdb_backend=gdb_backend)
    server = DAPServer(request_handler=request_handler)
    return gdb_backend, request_handler, server


def _run_server_loop(gdb_backend: GDBBackend, server: DAPServer):
    """Run the main server loop with proper error handling."""
    try:
        gdb_backend.start()
        server.start()
        print("Debug Adapter is running", flush=True)
        server.handle_requests()
    except KeyboardInterrupt:
        print("Shutting down Debug Adapter...")


def _cleanup(gdb_backend: GDBBackend, server: DAPServer):
    """Perform cleanup operations."""
    server.stop()
    gdb_backend.stop()
    print("Debug Adapter stopped...")


def main():
    """Entry point for the Debug Adapter server."""
    parser = argparse.ArgumentParser(description="Debug Adapter")
    parser.add_argument(
        "--gdb-path",
        type=str,
        default="/usr/bin/gdb",
        help="Path to the GDB executable",
    )
    args = parser.parse_args()

    print(f"Starting Debug Adapter with GDB Path: {args.gdb_path}", flush=True)

    gdb_backend, _, server = _setup_components(args.gdb_path)
    _run_server_loop(gdb_backend, server)
    _cleanup(gdb_backend, server)
