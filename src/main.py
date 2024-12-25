import argparse

from dap.request_handler import DAPRequestHandler
from dap.server import DAPServer
from gdb.backend import GDBBackend

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Debug Adapter")
    parser.add_argument(
        "--gdbPath",
        type=str,
        default="/usr/bin/gdb",
        help="Path to the GDB executable",
    )
    parser.add_argument(
        "--program",
        type=str,
        help="Path to the program to debug",
    )
    args = parser.parse_args()

    print(
        f"Starting Debug Adapter with GDB Path: {args.gdbPath} and Program: {args.program}",
    )

    HOST = "127.0.0.1"
    PORT = 4711

    gdb_backend = GDBBackend(gdb_path=args.gdbPath)
    request_handler = DAPRequestHandler(gdb_backend=gdb_backend)
    server = DAPServer(host=HOST, port=PORT, request_handler=request_handler)

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
