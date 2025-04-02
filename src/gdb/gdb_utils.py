"""Utility functions for GDB response handling."""

from common import CommandResult


def is_gdb_responses_successful_with_message(responses: list[dict]) -> CommandResult:
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


def is_success_response(resp: dict) -> bool:
    """
    Check if a GDB response indicates successful command execution.

    :param resp: Single response dictionary from GDB
    :return: True if the response indicates success (type=result and message=done),
             False otherwise
    """
    return resp.get("type") == "result" and resp.get("message") == "done"
