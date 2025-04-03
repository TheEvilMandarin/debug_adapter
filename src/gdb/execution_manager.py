"""
Module for managing execution control in GDB.

This module provides functions to control program execution,
such as stepping in, stepping out, pausing, and continuing execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from common import CommandResult
    from gdb.backend import GDBBackend

from gdb.gdb_utils import is_gdb_responses_successful_with_message


class ExecutionManager:
    """
    Manages execution control in a debugging session using GDB.

    This class provides methods for executing debugging commands such as
    stepping in, stepping out, continuing execution, and pausing.
    """

    def __init__(self, backend: GDBBackend):
        """
        Initialize the ExecutionManager.

        :param backend: An instance of GDBBackend for executing GDB commands.
        """
        self.backend = backend

    def execute_step_out(self, thread_id: int | None, single_thread: bool) -> tuple[bool, str]:
        """
        Execute the `finish` command in GDB after switching to the specified thread.

        :param thread_id: The ID of the thread to switch to before stepping out.
        :param single_thread: Whether to step out only in a single thread.
        :return: A tuple (success, message) indicating whether the command executed successfully.
        """
        if thread_id:
            success, message = self.backend.send_command_and_check_for_success(
                f"-thread-select {thread_id}",
            )
            if not success:
                return False, f"Failed to select thread {thread_id}: {message}"

        scheduler_mode = "on" if single_thread else "off"
        self.backend.send_command_and_get_result(f"set scheduler-locking {scheduler_mode}")

        return self.backend.send_command_and_check_for_success("finish &")

    def execute_step_in(self, thread_id: int | None) -> tuple[bool, str]:
        """
        Execute the `-exec-step` command in GDB after switching to the specified thread.

        :param thread_id: The ID of the thread to switch to before stepping in.
        :return: A tuple (success, message) indicating whether the command executed successfully.
        """
        if thread_id:
            success, message = self.backend.send_command_and_check_for_success(
                f"-thread-select {thread_id}",
            )
            if not success:
                return False, f"Failed to select thread {thread_id}: {message}"

        return self.backend.send_command_and_check_for_success("-exec-step")

    def execute_next(self, thread_id: int | None) -> tuple[bool, str]:
        """
        Execute the `-exec-next` command in GDB after switching to the specified thread.

        :param thread_id: The ID of the thread to switch to before stepping.
        :return: A tuple (success, message) indicating whether the command executed successfully.
        """
        if thread_id:
            success, message = self.backend.send_command_and_check_for_success(
                f"-thread-select {thread_id}",
            )
            if not success:
                return False, f"Failed to select thread {thread_id}: {message}"

        return self.backend.send_command_and_check_for_success("-exec-next")

    def pause_execution(self, thread_id: int | None = None) -> CommandResult:
        """Pause program execution."""
        if thread_id:
            self.backend.send_command_and_get_result(f"-thread-select {thread_id}")
        responses = self.backend.send_command_and_get_result("-exec-interrupt")

        return is_gdb_responses_successful_with_message(responses)

    def continue_execution(self, thread_id: int | None = None) -> CommandResult:
        """Continue program execution."""
        command = f"-exec-continue --thread {thread_id}" if thread_id else "-exec-continue"
        responses = self.backend.send_command_and_get_result(command)
        return is_gdb_responses_successful_with_message(responses)
