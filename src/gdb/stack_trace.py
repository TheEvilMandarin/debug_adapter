"""
Module for managing stack traces using GDB.

This module provides functionality to fetch and parse stack traces from GDB.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gdb.backend import GDBBackend

from gdb.gdb_utils import is_gdb_response_successful


# TODO: ignore (or do something else) with system files.
# A client (for example, vscode), if given a non-existent path to a file
# (for example, where it was created), will try to open it and encounter an error.
# TODO: Request a specified range of frames
class StackTraceManager:
    """Manages stack traces for threads using GDB."""

    def __init__(self, backend: GDBBackend):
        """
        Initialize the StackTraceManager.

        :param backend: An instance of GDBBackend for executing GDB commands.
        """
        self.backend: GDBBackend = backend

    def get_stack_trace(self, thread_id: int) -> tuple[bool, str, list[dict]]:
        """
        Return the call stack for the specified thread.

        :param thread_id: ID of the thread to fetch the stack trace for.
        :return: A tuple containing success status, message, and stack frames.
        """
        self.backend.send_command_and_get_result(f"-thread-select {thread_id}")
        responses = self.backend.send_command_and_get_result("-stack-list-frames")

        if not responses:
            return False, "No response from GDB", []

        stack_frames = self._parse_stack_frames(responses)
        success, message = is_gdb_response_successful(responses)
        return success, message, stack_frames

    def _parse_stack_frames(self, responses: list[dict]) -> list[dict]:
        """
        Parse stack frames from GDB responses.

        :param responses: List of responses from GDB.
        :return: List of parsed stack frames.
        """
        for msg in responses:
            if msg.get("type") == "result" and msg.get("message") == "done":
                payload = msg.get("payload", {})
                gdb_stack = payload.get("stack", [])
                return [self._parse_frame(frame_info) for frame_info in gdb_stack]
        return []

    # TODO: make vscode detect jit code
    def _parse_frame(self, frame_info: dict) -> dict:
        """
        Parse a single frame from GDB response.

        :param frame_info: Dictionary containing frame information.
        :return: A dictionary representing the parsed frame.
        """
        level = self._safe_int(frame_info.get("level"))
        line = self._safe_int(frame_info.get("line", "0"))

        file_name = frame_info.get("file", "<unknown>")
        fullname = frame_info.get("fullname", "")
        func_name = frame_info.get("func", "<unknown>")

        if fullname:
            source = {
                "name": file_name,
                "path": fullname,
            }
            pres_hint = "normal"
        else:
            source = {
                "name": file_name,
            }
            pres_hint = "subtle"  # Hint for UI that the frame is synthetic/special

        return {
            "id": level,
            "name": func_name,
            "source": source,
            "line": line,
            "column": 0,  # GDB does not provide columns, the default is 0
            "addr": frame_info.get("addr", ""),
            "arch": frame_info.get("arch", ""),
            "from": frame_info.get("from", ""),
            "presentationHint": pres_hint,
        }

    def _safe_int(self, value: str | None) -> int:
        """
        Safely convert a string to an integer.

        :param value: The string to convert.
        :return: The integer value or 0 if conversion fails.
        """
        try:
            return int(value) if value is not None else 0
        except ValueError:
            return 0
