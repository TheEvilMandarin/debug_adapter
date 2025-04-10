"""
Module for managing processes using GDB.

This module provides functionality to attach/detach processes,
list processes, and select inferiors by PID.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from common import CommandResult
from gdb.gdb_utils import is_gdb_responses_successful_with_message

if TYPE_CHECKING:
    from gdb.backend import GDBBackend


class ProcessManager:
    """
    Manages processes in a debugging session using GDB.

    This class interacts with the GDB backend to:
    - Attach to a process by PID
    - Detach from a process
    - Switch between inferiors
    - Get a list of OS processes
    - Load program symbols
    """

    def __init__(self, backend: GDBBackend):
        """
        Initialize the ProcessManager.

        :param backend: An instance of GDBBackend for executing GDB commands.
        """
        self.backend = backend

    def attach_to_process(self, pid: int, program_path: str = "") -> CommandResult:
        """
        Connect to a process by its PID.

        It first checks whether the process is already managed by GDB using
        `-list-thread-groups`. If the process is not found, it issues the `attach` command.
        After attaching, it verifies that the process is correctly registered in GDB
        and removes any unused inferiors if necessary. Finally, it attempts to load
        symbols from the provided `program_path`.
        """
        # List of current inferiors
        groups = self._get_thread_groups()
        # Attempt to find the target inferior
        target_inferior = self._find_target_inferior(groups, pid)

        # If the target process is not already managed by GDB, attach to it
        if not target_inferior:
            success, message = self.backend.send_command_and_check_for_success(f"attach {pid}")
            if not success:
                return CommandResult(success, f"Failed to attach to PID {pid}: {message}")

        # Verify that the attached process is now recognized by GDB and remove any unused inferiors
        success, message = self.check_pid_in_inferiors_and_remove_unused(pid)
        if not success:
            return CommandResult(success, f"Failed to attach to PID {pid}: {message}")

        # Load debugging symbols for the target program
        return self.load_program_symbols(program_path)

    def check_pid_in_inferiors_and_remove_unused(
        self,
        attached_pid: int,
    ) -> tuple[bool, str]:
        """
        Process GDB responses to manage inferiors.

        This function parses GDB's response to check whether the attached PID is
        listed among the inferiors. If it is found, it ensures that the correct
        inferior is active and detaches any other unnecessary inferiors.
        """
        groups = self._get_thread_groups()
        if not groups:
            return False, "No response from GDB"

        # Identify the target inferior associated with the attached PID
        target_inferior = self._find_target_inferior(groups, attached_pid)
        if not target_inferior:
            return False, f"No inferior found for PID {attached_pid}"

        # Switch to the target inferior and detach unnecessary ones
        return self._switch_to_target_inferior_and_detach_others(target_inferior, groups)

    def get_processes(self) -> tuple[CommandResult, list[dict]]:
        """Request a list of processes."""
        command = "-info-os processes"
        result = self.backend.send_command_and_get_result(command)
        success, message = is_gdb_responses_successful_with_message(result)
        return CommandResult(success, message), self.parse_processes(result)

    def parse_processes(self, result: list[dict]) -> list[dict]:
        """Extract a list of processes from the output of a GDB command."""
        if not result:
            return []
        first_result = result[0]
        os_data = first_result.get("payload", {}).get("OSDataTable")
        if not os_data:
            return []

        processes = []
        for row in os_data.get("body", []):
            if "col0" in row and "col1" in row:
                pid = int(row["col0"])
                name = row["col1"]
                processes.append({"pid": pid, "name": name})

        return processes

    def get_pid_by_name(self, process_name: str) -> int | None:
        """Get PID of a process by its name."""
        result, processes = self.get_processes()
        if not result.success:
            return None

        for proc in processes:
            if proc.get("name") == process_name:
                return proc.get("pid", None)

        return None

    def _extract_pid_from_target_id(self, target_id: str) -> int | None:
        # parse format "Thread <pid>.<tid>"
        match = re.search(r"Thread (\d+)\.(\d+)", target_id)
        if match:
            return int(match.group(1))
        # parse format "(LWP NNN)"
        match_lwp = re.search(r"\(LWP (\d+)\)", target_id)
        if match_lwp:
            return int(match_lwp.group(1))
        return None

    def get_current_pid(self) -> int | None:
        """Get the PID of the current (active) process."""
        command = "-thread-info"
        result = self.backend.send_command_and_get_result(command)
        if not result:
            return None

        payload = result[0].get("payload", {})
        current_thread_id = payload.get("current-thread-id")
        threads = payload.get("threads", [])

        if not current_thread_id or not threads:
            return None

        current_thread = next(
            (thread for thread in threads if thread.get("id") == current_thread_id),
            None,
        )
        if not current_thread:
            return None

        return self._extract_pid_from_target_id(current_thread.get("target-id", ""))

    def add_inferior_with_pids(self, pids: list[int]) -> None:
        """Add inferiors for all passed PIDs, attach processes and return the initial inferior."""
        if not pids:
            print("No PIDs provided", flush=True)
            return

        current_inferior = self.get_current_inferior()
        if not current_inferior:
            print("Failed to determine current inferior", flush=True)
            return

        new_inferiors = self._create_inferiors_for_pids(pids)
        self._attach_pids_to_inferiors(new_inferiors)
        # Switch back to the original inferior
        self._switch_inferior(current_inferior)

    def _create_inferiors_for_pids(self, pids: list[int]) -> dict[int, int]:
        """Create new inferiors for each PID."""
        new_inferiors = {}
        for pid in pids:
            responses = self.backend.send_command_and_get_result("add-inferior")
            new_inferior = self._extract_inferior_number(responses)
            if new_inferior:
                new_inferiors[pid] = new_inferior
            else:
                print(f"Failed to create inferior for PID {pid}", flush=True)
        return new_inferiors

    def _attach_pids_to_inferiors(self, pid_inferior_map: dict[int, int]) -> None:
        """Attach each PID to its corresponding inferior."""
        for pid, inferior in pid_inferior_map.items():
            if self._switch_to_inferior(inferior):
                self._attach_to_inferior(pid)

    def _switch_to_inferior(self, inferior: int) -> bool:
        """Switch to inferior."""
        success, _ = self.backend.send_command_and_check_for_success(f"inferior {inferior}")
        return success

    def _attach_to_inferior(self, pid: int) -> bool:
        """Attach PID."""
        success, _ = self.backend.send_command_and_check_for_success(f"attach {pid}")
        return success

    def detach_inferiors_with_pids(self, pids: list[int]) -> None:
        """Remove inferiors for all passed PIDs."""
        if not pids:
            return

        current_inferior = self.get_current_inferior()
        groups = self._get_thread_groups()
        if not groups:
            return

        pid_to_inferior = self._map_pids_to_inferiors(groups, pids)
        if not pid_to_inferior:
            return

        self._handle_current_inferior(current_inferior, set(pid_to_inferior.values()), groups)
        self._remove_inferiors(pid_to_inferior)

    def _get_thread_groups(self) -> list[dict]:
        responses = self.backend.send_command_and_get_result("-list-thread-groups")
        if not responses:
            return []

        for response in responses:
            if response.get("type") == "result" and response.get("message") == "done":
                payload = response.get("payload", {})
                return payload.get("groups", [])

        return []

    def _map_pids_to_inferiors(self, groups: list[dict], pids: list[int]) -> dict[int, int]:
        """Create mapping from PID to inferior number."""
        pid_to_inferior = {}
        for group in groups:
            pid_str = group.get("pid")
            inf_id = group.get("id")
            if pid_str and pid_str.isdigit() and inf_id and int(pid_str) in pids:
                pid_to_inferior[int(pid_str)] = inf_id.lstrip("i")
        return pid_to_inferior

    def _handle_current_inferior(
        self,
        current_inferior: str | None,
        remove_inferiors: set[int],
        groups: list[dict],
    ) -> None:
        """Handle case when current inferior is in remove list."""
        if current_inferior and current_inferior in remove_inferiors:
            other_inferior = self._find_other_inferior(groups, remove_inferiors)
            if other_inferior:
                self._switch_inferior(other_inferior)
            else:
                self._detach_current_inferior()

    def _find_other_inferior(
        self,
        groups: list[dict],
        remove_inferiors: set[int],
    ) -> str | None:
        """Find inferior not in remove list."""
        for group in groups:
            inf_id = group.get("id")
            if inf_id:
                inf_num = inf_id.lstrip("i")
                if inf_num not in remove_inferiors:
                    return inf_num
        return None

    def _switch_inferior(self, inferior_number: str) -> None:
        """Switch to specified inferior."""
        self.backend.send_command_and_get_result(f"inferior {inferior_number}")

    def _detach_current_inferior(self) -> None:
        """Detach current inferior."""
        self.backend.send_command_and_get_result("detach")

    def _remove_inferiors(self, pid_to_inferior: dict[int, int]) -> None:
        for inf_num in pid_to_inferior.values():
            self._detach_inferior(inf_num)
            self._remove_inferior(inf_num)

    def _detach_inferior(self, inferior_number: int) -> None:
        """Detach specified inferior."""
        self.backend.send_command_and_check_for_success(f"detach inferior {inferior_number}")

    def _remove_inferior(self, inferior_number: int) -> None:
        """Remove specified inferior."""
        self.backend.send_command_and_get_result(
            f"remove-inferior {inferior_number}",
        )

    def select_inferior_by_pid(self, pid: int) -> bool:
        """Switches to the inferior associated with the given PID."""
        groups = self._get_thread_groups()
        if not groups:
            return False

        target_inferior = None
        for group in groups:
            pid_str = group.get("pid")
            if pid_str and pid_str.isdigit() and int(pid_str) == pid:
                target_inferior = group.get("id")
                break

        if not target_inferior:
            print(f"No inferior found for PID {pid}", flush=True)
            return False

        if target_inferior.startswith("i"):
            target_inferior = target_inferior[1:]

        success, _ = self.backend.send_command_and_check_for_success(
            f"inferior {target_inferior}",
        )
        return success

    def connect_to_gdbserver(self, gdb_server_address: str) -> CommandResult:
        """
        Connect to gdbserver at a given address.

        :param gdb_server_address: gdbserver address.
        """
        command = f"target extended-remote {gdb_server_address}"
        responses = self.backend.send_command_and_get_result(command)
        success, message = is_gdb_responses_successful_with_message(responses)
        if success:
            self.backend.send_shared_gdb_gdbserver_settings()
        self.backend.send_command_and_get_result("detach")
        return CommandResult(success, message)

    def load_program_symbols(self, program_path: str) -> CommandResult:
        """Load the program symbols into the debugger."""
        if program_path:
            if not Path(program_path).exists():
                return CommandResult(
                    success=False,
                    message=f"The path {program_path} does not exist",
                )
            command = f"file {program_path}"
            self.backend.send_command_and_get_result(command)
        return CommandResult(success=True, message="")

    def _find_target_inferior_and_groups(
        self,
        responses: list[dict],
        pid: int,
    ) -> tuple[str | None, list[dict]]:
        """
        Extract the target inferior ID for the specified PID.

        Parses GDB's response to locate the inferior ID associated with the given PID.
        If found, it returns both the inferior ID and the list of all inferiors.
        """
        for response in responses:
            if response.get("type") == "result" and response.get("message") == "done":
                groups = response.get("payload", {}).get("groups", [])
                target_inferior = self._find_target_inferior(groups, pid)
                return target_inferior, groups

        return None, []

    def _find_target_inferior(self, groups: list[dict], attached_pid: int) -> str | None:
        """Find the inferior ID corresponding to the given PID."""
        for group in groups:
            pid_int = self._extract_pid(group)
            if pid_int == attached_pid:
                return group.get("id")
        return None

    def _extract_pid(self, group: dict) -> int | None:
        """Extract and converts the PID to int if possible."""
        if group.get("type") != "process":
            return None

        pid = group.get("pid")
        if pid is None:
            return None
        try:
            return int(pid)
        except ValueError:
            return None

    def _switch_to_target_inferior_and_detach_others(
        self,
        target_inferior: str,
        groups: list[dict],
    ) -> tuple[bool, str]:
        """Switch to the correct inferior and detach others."""
        inferior_number = target_inferior.lstrip("i")
        if not self._execute_inferior_switch(inferior_number):
            return False, f"Failed to switch to inferior {inferior_number}"
        return self._detach_other_inferiors(target_inferior, groups)

    def _execute_inferior_switch(self, inferior_number: str) -> bool:
        """Execute the inferior switch command."""
        switch_responses = self.backend.send_command_and_get_result(f"inferior {inferior_number}")
        success, _ = is_gdb_responses_successful_with_message(switch_responses)
        return success

    def _detach_other_inferiors(self, target_inferior: str, groups: list[dict]) -> tuple[bool, str]:
        """Detach all inferiors except the target."""
        for group in groups:
            inferior_id = group.get("id")
            if inferior_id is None or inferior_id == target_inferior:
                continue

            inferior_number = inferior_id.lstrip("i")
            detach_command = f"detach inferior {inferior_number}"
            detach_responses = self.backend.send_command_and_get_result(detach_command)
            success, message = is_gdb_responses_successful_with_message(detach_responses)

            if not success:
                return False, f"Failed to detach inferior {inferior_id}: {message}"

        return True, ""

    def get_inferiors_list(self) -> list:
        """Get inferiors list."""
        groups = self._get_thread_groups()
        if not groups:
            return []

        # Filter out groups that don't have a PID (inactive processes)
        active_inferiors = [group for group in groups if "pid" in group]

        if not active_inferiors:
            return []

        return active_inferiors

    def get_current_inferior(self) -> str | None:
        """
        Determine the current inferior by matching the current thread's PID with inferiors.
        If current PID is not available, returns the first available inferior.
        Returns None only if no inferiors are available.
        """
        groups = self.get_inferiors_list()
        if not groups:
            return None

        current_pid = self.get_current_pid()
        if not current_pid:
            first_inferior = groups[0]
            inferior_id = first_inferior.get("id", "")
            inferior_id_number = inferior_id[1:]
            self.backend.send_command_and_get_result(f"inferior {inferior_id_number}")
            return inferior_id_number

        for group in groups:
            pid_str = group.get("pid")
            if pid_str and pid_str.isdigit() and int(pid_str) == current_pid:
                inferior_id = group.get("id", "")
                if inferior_id.startswith("i"):
                    return inferior_id[1:]
                return inferior_id

        return None

    def _extract_inferior_number(self, responses: list[dict]) -> int | None:
        """Extract the inferior number from the response to the "add-inferior" command."""
        for response in responses:
            if response.get("type") == "console":
                match = re.search(r"Added inferior (\d+)", response.get("payload", ""))
                if match:
                    return int(match.group(1))
        return None
