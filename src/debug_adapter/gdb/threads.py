"""
Module for managing threads using GDB.

This module provides functionality to retrieve and parse thread information from GDB.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from debug_adapter.gdb.backend import GDBBackend

from debug_adapter.gdb.gdb_utils import is_gdb_responses_successful_with_message


class ThreadManager:
    """
    Manages threads in a debugging session using GDB.

    This class interacts with the GDB backend to fetch and process
    thread information.
    """

    def __init__(self, backend: GDBBackend):
        """
        Initialize the ThreadManager.

        :param backend: An instance of GDBBackend for executing GDB commands.
        """
        self.backend: GDBBackend = backend

    # TODO: get more correct names of threads.
    # Now the thread name is returned as the actual thread name.
    # Think about how to return it more correctly:
    # (for example, the name of the program being launched + the name of the thread).
    def get_threads(self) -> tuple[bool, str, list[dict]]:
        """Return a list of threads managed by GDB."""
        responses = self.backend.send_command_and_get_result("-thread-info")

        success, error_message = is_gdb_responses_successful_with_message(responses)
        threads = self._extract_threads(responses) if success else []
        return success, error_message, threads

    def _extract_threads(self, responses: list[dict]) -> list[dict]:
        """Extract thread information from GDB responses."""
        if not responses:
            return []
        for resp in responses:
            payload = resp.get("payload", {})
            if not isinstance(payload, dict):
                return []
            return self._parse_threads(payload.get("threads", []))
        return []

    def _parse_threads(self, threads: list[dict]) -> list[dict]:
        """Parse thread details from GDB payload."""
        if not threads:
            return []
        keys = ["target-id", "name", "frame", "details", "state", "core"]
        return [
            {
                "id": int(thread["id"]),
                **{key: self._get_thread_value(thread, key) for key in keys},
            }
            for thread in threads
        ]

    def _get_thread_value(self, thread, key, default_prefix="Thread") -> dict:
        return thread.get(key, f"{default_prefix} {thread['id']}")
