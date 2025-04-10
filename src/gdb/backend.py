"""GDBBackend module: Manage debugging through GDB using Debug Adapter Protocol (DAP)."""

import threading
import time
from queue import Empty, Queue
from typing import Any

from pygdbmi.gdbcontroller import GdbController

from common import CommandResult
from dap.notifier import DAPNotifier, NullNotifier
from gdb.breakpoints import BreakpointManager
from gdb.execution_manager import ExecutionManager
from gdb.gdb_utils import is_gdb_responses_successful_with_message
from gdb.processes import ProcessManager
from gdb.stack_trace import StackTraceManager
from gdb.threads import ThreadManager
from gdb.variables import VariableManager

DEFAULT_TIMEOUT_WAITING_RESPONSE_FROM_GDB = 20.0


class GDBBackend:
    """Class for interacting with GDB via pygdbmi."""

    def __init__(self, gdb_path: str):
        """
        Initialize the GDBBackend.

        :param gdb_path: Path to the GDB executable.
        """
        self._gdb_lock = threading.Lock()
        self._gdb_path: str = gdb_path
        self._gdbmi: GdbController | None = None
        self._stop_monitoring = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self._notifier: DAPNotifier = NullNotifier()
        self._response_queue: Queue[dict[str, Any]] = Queue()

        self.breakpoint_manager = BreakpointManager(self)
        self.stack_trace_manager = StackTraceManager(self)
        self.variable_manager = VariableManager(self)
        self.thread_manager = ThreadManager(self)
        self.execution_manager = ExecutionManager(self)
        self.process_manager = ProcessManager(self)

    def start(self):
        """Start GDB and performs basic setup."""
        self._gdbmi = GdbController(
            command=[self._gdb_path, "--nx", "--quiet", "--interpreter=mi3"],
        )
        self._start_monitoring()
        self._send_initial_commands()
        self.send_shared_gdb_gdbserver_settings()

    def stop(self):
        """Stop GDB and terminates the process."""
        self._stop_monitoring.set()
        if self._monitor_thread:
            self._monitor_thread.join()
        if self._gdbmi:
            self._gdbmi.exit()
            self._gdbmi = None

    @property
    def notifier(self) -> DAPNotifier:
        """Get the DAPNotifier."""
        return self._notifier

    @notifier.setter
    def notifier(self, value: DAPNotifier):
        """Set the DAPNotifier."""
        self._notifier = value

    def _start_monitoring(self):
        """Start a thread to monitor the state of GDB."""
        self._stop_monitoring.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_gdb_events, daemon=True)
        self._monitor_thread.start()

    def _monitor_gdb_events(self):
        """Background process for monitoring GDB events."""
        while not self._stop_monitoring.is_set():
            responses = self._get_gdb_responses()
            for response in responses:
                self._process_gdb_response(response)
            time.sleep(0.1)

    def _get_gdb_responses(self) -> list:
        """
        Fetch responses from GDB.

        Raises:
            RuntimeError: If GDB is not running (self.gdbmi is None).
        """
        if not self._gdbmi:
            raise RuntimeError("GDB is not running")

        return self._gdbmi.get_gdb_response(raise_error_on_timeout=False)

    def _process_gdb_response(self, response: dict):
        """Process individual GDB response."""
        print(f"response: {response}", flush=True)

        if self._is_notify_event(response, "stopped"):
            self._handle_stop_event(response)
        elif self._is_notify_event(response, "running"):
            self._handle_continue_event(response)
        else:
            self._response_queue.put(response)

    def _is_notify_event(self, response: dict, message: str) -> bool:
        """Check if the response is a 'notify' event with a specific message."""
        return response.get("type") == "notify" and response.get("message") == message

    def _handle_stop_event(self, response: dict):
        """Handle a GDB stop and sends a `stopped` event to the DAP."""
        payload = response.get("payload", {})

        if "new-exec" in payload:
            self.notifier.send_new_process_event()
            return

        stop_reason = payload.get("reason", "unknown")
        default_thread_id = 1
        thread_id = int(payload.get("thread-id", default_thread_id))
        hit_breakpoints = []
        if "breakpoint" in stop_reason:
            breakpoint_number = payload.get("bkptno")
            if breakpoint_number:
                hit_breakpoints.append(int(breakpoint_number))

        if "exited" in stop_reason:
            self.notifier.send_exited_process_event()
            return
        self.notifier.send_stopped_event(
            reason=stop_reason,
            thread_id=thread_id,
            all_threads_stopped=payload.get("stopped-threads") == "all",
            hit_breakpoint_ids=hit_breakpoints,
        )

    def _handle_continue_event(self, response: dict):
        """Handle the continuation of program execution and send the `continue` event to the DAP."""
        payload = response.get("payload", {})
        thread_id = payload.get("thread-id", "")

        self.notifier.send_continued_event(
            thread_id=thread_id,
            all_threads_continued=response.get("continued-threads") == "all"
            or thread_id == "all",
        )

        self.notifier.send_invalidated_event(areas=["stacks"])

    def send_command_and_get_result(
        self,
        command: str,
        timeout: float = DEFAULT_TIMEOUT_WAITING_RESPONSE_FROM_GDB,
        expected_response=("done", "error", "running"),
    ) -> list[dict]:
        """
        Send a command to GDB and wait for the response.

        This method sends a command to the GDB process and waits for the response
        within the specified timeout. It clears the response queue before sending
        the command and reads responses until an expected response is received.

        It is preferable to call this command instead of _send_command,
        since there is often no point in calling the next command until the current one is executed.

        Raises:
            RuntimeError: If GDB is not running (self._gdbmi is None).

        Args:
            command (str): The GDB/MI command to send (e.g., "-break-insert main").
            timeout (float): Maximum time (in seconds) to wait for a response.
            expected_response (tuple[str, ...]): A tuple of expected response types.

        Returns:
            list[dict]: A list of responses from GDB. Each response is a dictionary
                containing the GDB/MI output.
        """
        if not self._gdbmi:
            raise RuntimeError("GDB is not running")

        self._clear_response_queue()
        self._send_command(command)
        return self._read_responses_from_queue(timeout, expected_response)

    def _send_command(self, command: str) -> None:
        print(f"Sending command to gdb: {command}", flush=True)
        if not self._gdbmi:
            raise RuntimeError("GDB is not running")
        with self._gdb_lock:
            self._gdbmi.write(command, read_response=False)

    def _read_responses_from_queue(
        self,
        timeout: float,
        expected_response: tuple,
        expected_type="result",
    ) -> list[dict]:
        """Read responses from the GDB queue within the specified timeout."""
        start_time = time.time()
        all_responses = []

        while time.time() - start_time <= timeout:
            try:
                response = self._response_queue.get(timeout=0.1)
            except Empty:
                continue

            all_responses.append(response)

            if self._has_response_of_interest(response, expected_response, expected_type):
                return all_responses

        return self._handle_timeout_error(timeout)

    def _handle_timeout_error(self, timeout: float) -> list[dict]:
        """Generate an error message when the response timeout is exceeded."""
        error_message = f"Expected response not received within {timeout} seconds for command."
        return [
            {
                "type": "result",
                "message": "error",
                "payload": {"msg": error_message},
                "token": None,
                "stream": "stdout",
            },
        ]

    def _clear_response_queue(self) -> None:
        """Clear the GDB response queue."""
        while not self._response_queue.empty():
            try:
                self._response_queue.get_nowait()
            except Empty:
                break

    def _process_part_answer(self, part_answer: list[dict], expected_response: tuple) -> list[dict]:
        """Process a part of the GDB response."""
        all_responses = []
        for response in part_answer:
            all_responses.append(response)
            if self._has_response_of_interest(response, expected_response):
                return all_responses
        return all_responses

    def _read_responses(self, timeout: float, expected_response: tuple, command: str) -> list[dict]:
        start_time = time.time()
        all_responses = []

        if not self._gdbmi:
            raise RuntimeError("GDB is not running")

        while time.time() - start_time <= timeout:
            part_answer = self._gdbmi.get_gdb_response(raise_error_on_timeout=False)
            if part_answer:
                processed_responses = self._process_part_answer(part_answer, expected_response)
                all_responses.extend(processed_responses)
                if len(processed_responses) < len(part_answer):
                    return all_responses

        error_message = (
            f"Expected response not received within {timeout} seconds " f"for command '{command}'."
        )
        payload = {"msg": error_message}
        result = {
            "type": "result",
            "message": "error",
            "payload": payload,
            "token": None,
            "stream": "stdout",
        }

        return [result]

    def _has_response_of_interest(
        self,
        response: dict,
        expected_response: tuple,
        expected_type="result",
    ) -> bool:
        """Check whether the response contains one of the expected values."""
        return (
            response.get("type") == expected_type and response.get("message") in expected_response
        )

    def send_command_and_check_for_success(
        self,
        command: str,
        ignore_failures: bool = False,
    ) -> CommandResult:
        """Send a command to GDB and checks if the response indicates success."""
        responses = self.send_command_and_get_result(command)

        if not ignore_failures:
            return is_gdb_responses_successful_with_message(responses)
        success = True
        return CommandResult(success, "")

    def select_frame(self, frame_id: str) -> CommandResult:
        """Select a specific stack frame in the debugging session."""
        return self.send_command_and_check_for_success(f"-stack-select-frame {frame_id}")

    def _send_initial_commands(self):
        """Perform initial GDB setup."""
        self.send_command_and_get_result("-gdb-set mi-async on")
        self.send_command_and_get_result("-gdb-set confirm off")
        self.send_command_and_get_result("-enable-pretty-printing")
        self.send_command_and_get_result("set pagination off")
        self.send_command_and_get_result("set auto-solib-add on")
        print("GDB initialized and configured.", flush=True)

    # TODO: Make it user configurable
    def send_shared_gdb_gdbserver_settings(self):
        """Set common settings for gdb and gdb server"""
        self.send_command_and_get_result("set osabi auto")
        self.send_command_and_get_result("set follow-fork-mode parent")
        self.send_command_and_get_result("set follow-exec-mode same")
        self.send_command_and_get_result("set detach-on-fork off")

        # `set scheduler-locking off` and `set schedule-multiple on` are useful for gdbserver,
        # because they allow threads to execute in parallel.
        # In local GDB this may not work due to limitations of ptrace().
        # but the command is harmless, we simply ignore it if there is no effect.
        self.send_command_and_get_result("set scheduler-locking off")
        self.send_command_and_get_result("set schedule-multiple on")
