"""
Module for managing breakpoints in GDB.

This module provides functions to set, clear, and retrieve breakpoint locations using GDB.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from debug_adapter.common import CommandResult
    from debug_adapter.gdb.backend import GDBBackend

from debug_adapter.gdb.gdb_utils import is_gdb_responses_successful_with_message


class BreakpointManager:
    """
    Manages breakpoints in a debugging session using GDB.

    This class provides methods for setting, clearing, and retrieving
    breakpoints in the debugging process.
    """

    def __init__(self, backend: GDBBackend):
        """
        Initialize the BreakpointManager.

        :param backend: An instance of GDBBackend for executing GDB commands.
        """
        self.backend: GDBBackend = backend

    def get_breakpoint_locations(
        self,
        source_path: str,
        line: int,
        end_line: int | None = None,
    ) -> tuple[bool, str, list[dict]]:
        """
        Get possible lines for setting a breakpoint in a file.

        :param source_path: Path to the source file.
        :param line: The specific line to check for breakpoints.
        :param end_line: Optional end line for a range of breakpoints.
        :return: A tuple (success, message, list of possible breakpoint locations).
        """
        responses = self.backend.send_command_and_get_result(f"-symbol-list-lines {source_path}")

        success, message = is_gdb_responses_successful_with_message(responses)
        if not success:
            return False, message, []

        possible_lines = self._extract_possible_lines(responses, line, end_line)
        return True, "", [{"line": line} for line in sorted(possible_lines)]

    def _extract_possible_lines(
        self,
        responses: list[dict],
        line: int,
        end_line: int | None,
    ) -> set:
        """
        Extract possible breakpoint lines from GDB responses.

        :param responses: GDB response list.
        :param line: Target line.
        :param end_line: Optional end line for range.
        :return: Set of possible line numbers.
        """
        possible_lines = set()
        for response in responses:
            if response.get("type") == "result" and response.get("message") == "done":
                lines_info = response.get("payload", {}).get("lines", [])
                possible_lines.update(self._filter_lines(lines_info, line, end_line))
        return possible_lines

    def _filter_lines(self, lines_info: list[dict], line: int, end_line: int | None) -> set:
        """
        Filter lines based on given constraints.

        :param lines_info: List of lines from GDB.
        :param line: Target line.
        :param end_line: Optional end line for range.
        :return: Set of filtered line numbers.
        """
        return {
            int(entry["line"]) for entry in lines_info if self._is_valid_line(entry, line, end_line)
        }

    def _is_valid_line(self, entry: dict, line: int, end_line: int | None) -> bool:
        """
        Check if a line entry is valid for breakpoints.

        :param entry: Line entry from GDB.
        :param line: Target line.
        :param end_line: Optional end line for range.
        :return: True if valid, False otherwise.
        """
        this_line = int(entry["line"])
        return (end_line is None and this_line == line) or (
            end_line is not None and line <= this_line <= end_line
        )

    def set_breakpoints(
        self,
        source_path: str,
        breakpoints: list[dict],
    ) -> tuple[bool, str, list[dict]]:
        """Set breakpoints in GDB for the specified file."""
        responses = []
        result_breakpoints = []

        for bp in breakpoints:
            line = bp.get("line")
            if line is None:
                continue

            response = self.backend.send_command_and_get_result(
                f"-break-insert {source_path}:{line}",
            )
            responses.extend(response)

            success, message = is_gdb_responses_successful_with_message(response)

            result_breakpoints.append(
                {
                    "verified": success,
                    "line": line,
                    "source": {"path": source_path},
                    "message": "" if success else message,
                },
            )

        return True, "", result_breakpoints

    def set_breakpoint_on_main(self) -> CommandResult:
        """Set breakpoint in GDB on main function."""
        return self.backend.send_command_and_check_for_success(
            "-break-insert main",
        )

    def clear_breakpoints(self, source_path: str):
        """
        Remove all breakpoints in the specified file.

        :param source_path: Path to the source file.
        """
        responses = self.backend.send_command_and_get_result("-break-list")

        breakpoints = self._get_breakpoints_from_response(responses, source_path)
        self._delete_breakpoints(breakpoints)

    def set_exec_catchpoint(self):
        """
        Set a catchpoint in GDB to pause execution when the program
        performs an exec() system call.
        """
        self.backend.send_command_and_get_result("catch exec")

    def _get_breakpoints_from_response(self, responses: list[dict], source_path: str) -> list[str]:
        """
        Extract breakpoint numbers from GDB responses.

        :param responses: List of GDB responses.
        :param source_path: Path to the source file.
        :return: List of breakpoint numbers to delete.
        """
        for response in responses:
            if response.get("type") != "result" or response.get("message") != "done":
                continue  # Skip invalid answers

            breakpoint_table = response.get("payload", {}).get("BreakpointTable", {})
            breakpoints = breakpoint_table.get("body", [])

            return [
                bp.get("number")
                for bp in breakpoints
                if bp.get("fullname") == source_path and bp.get("number")
            ]

        return []

    def _delete_breakpoints(self, breakpoints: list[str]):
        """
        Delete breakpoints by their numbers.

        :param breakpoints: List of breakpoint numbers.
        """
        for bp_number in breakpoints:
            self.backend.send_command_and_get_result(f"-break-delete {bp_number}")
