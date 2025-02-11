"""Utility functions for GDB response handling."""

from common import CommandResult


def is_gdb_response_successful(responses: list[dict]) -> CommandResult:
    """
    Parse GDB responses for errors.

    :param responses: List of responses from GDB.
    :return: Tuple (success, error_message).
    """
    for resp in responses:
        if resp.get("type") == "result" and resp.get("message") == "error":
            success = False
            error_message = resp["payload"].get("msg", "Unknown error")
            return CommandResult(success, f"Error from GDB: {error_message}")
    success = True
    return CommandResult(success, "")
