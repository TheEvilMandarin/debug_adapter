"""Entry point for the Debug Adapter Protocol (DAP) server."""

import argparse

from dap.request_handler import DAPRequestHandler
from dap.server import DAPServer
from gdb.backend import GDBBackend

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Debug Adapter")
    parser.add_argument(
        "--gdb-path",
        type=str,
        default="/usr/bin/gdb",
        help="Path to the GDB executable",
    )
    parser.add_argument(
        "--program",
        type=str,
        default="",
        help="Path to the program to debug",
    )
    args = parser.parse_args()

    print(
        f"Starting Debug Adapter with GDB Path: {args.gdb_path} and Program: {args.program}",
    )

    gdb_backend = GDBBackend(gdb_path=args.gdb_path)
    request_handler = DAPRequestHandler(gdb_backend=gdb_backend)
    server = DAPServer(request_handler=request_handler)

    try:
        gdb_backend.start()
        server.start()
        print("Debug Adapter is running", flush=True)
        server.handle_requests()
    except KeyboardInterrupt:
        print("Shutting down Debug Adapter...")
    finally:
        server.stop()
        gdb_backend.stop()
        print("Debug Adapter stopped...")
