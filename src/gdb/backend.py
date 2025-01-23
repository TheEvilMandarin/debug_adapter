import time
from pathlib import Path

from pygdbmi.gdbcontroller import GdbController

TYPE = "type"
MESSAGE = "message"
PAYLOAD = "payload"
ID = "id"
RESULT = "result"


class GDBBackend:
    """Class for interacting with GDB via pygdbmi."""

    def __init__(self, gdb_path: str):
        """
        Initialize the GDBBackend.

        :param gdb_path: Path to the GDB executable.
        """
        self.gdb_path: str = gdb_path
        self.gdbmi: GdbController | None = None

    def start(self):
        """Start GDB and performs basic setup."""
        self.gdbmi = GdbController(
            command=[self.gdb_path, "--nx", "--quiet", "--interpreter=mi3"],
        )
        self._send_initial_commands()

    def stop(self):
        """Stop GDB and terminates the process."""
        if self.gdbmi:
            self.gdbmi.exit()
            self.gdbmi = None

    def send_command_and_get_result(
        self,
        command: str,
        timeout: float = 20.0,
        expected_response=("done", "error"),
    ) -> list[dict]:
        """
        Send a command and reads responses until it encounters
        'done' or 'error' (or until the timeout expires).

        Raises:
            RuntimeError: If GDB is not running.
        """
        if not self.gdbmi:
            raise RuntimeError("GDB is not running")

        self._send_command(command)
        return self._read_responses(timeout, expected_response, command)

    def _send_command(self, command: str) -> None:
        print(f"Sending command to gdb: {command}", flush=True)
        if not self.gdbmi:
            raise RuntimeError("GDB is not running")
        self.gdbmi.write(command, read_response=False)

    def _read_responses(self, timeout: float, expected_response: tuple, command: str) -> list[dict]:
        start_time = time.time()
        all_responses = []

        if not self.gdbmi:
            raise RuntimeError("GDB is not running")

        while time.time() - start_time <= timeout:
            part_answer = self.gdbmi.get_gdb_response(
                raise_error_on_timeout=False,
            )
            if part_answer:
                all_responses.extend(part_answer)
                if self._has_response_of_interest(part_answer, expected_response):
                    return all_responses

        error_message = (
            f"Expected response not received within {timeout} seconds "
            f"for command '{command}'."
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
        self, responses: list[dict], expected_response: tuple,
    ) -> bool:
        for resp in responses:
            if resp.get("type") == RESULT and resp.get("message") in expected_response:
                return True
        return False

    def send_command_and_check_for_success(
        self,
        command: str,
        ignore_failures: bool = False,
    ) -> tuple[bool, str]:
        """Send a command to GDB and checks if the response indicates success."""
        responses = self.send_command_and_get_result(command)

        if not ignore_failures:
            return _is_gdb_response_successful(responses)
        return True, ""

    def attach_to_process(self, pid: int, program_path: str = "") -> tuple[bool, str]:
        """Connect to a process by its PID."""
        success, message = self.send_command_and_check_for_success(f"attach {pid}")
        if success:
            return self.load_program_symbols(program_path)

        return success, message

    # TODO: get more correct names of threads.
    # Now the thread name is returned as the actual thread name.
    # Think about how to return it more correctly:
    # (for example, the name of the program being launched + the name of the thread).
    def get_threads(self) -> tuple[bool, str, list[dict]]:
        """Return a list of threads managed by GDB."""
        responses = self.send_command_and_get_result("-thread-info")

        success, error_message = _is_gdb_response_successful(responses)
        threads = self._extract_threads(responses) if success else []
        return success, error_message, threads

    def continue_execution(self, thread_id: int | None = None) -> tuple[bool, str]:
        """Continue program execution."""
        command = (
            f"-exec-continue --thread {thread_id}" if thread_id else "-exec-continue"
        )
        responses = self.send_command_and_get_result(command)
        return _is_gdb_response_successful(responses)

    def pause_execution(
        self,
        thread_id: int | None = None,
    ) -> tuple[bool, str, dict]:
        """Pause program execution."""
        if thread_id:
            self.send_command_and_get_result(f"-thread-select {thread_id}")
        responses = self.send_command_and_get_result("-exec-interrupt")

        success, message = _is_gdb_response_successful(responses)
        gdb_response: dict = {}

        for response in responses:
            is_notify = response.get(TYPE) == "notify"
            is_stopped = response.get(MESSAGE) == "stopped"
            if is_notify and is_stopped:
                gdb_response = response.get(PAYLOAD, {})
                break

        return success, message, gdb_response

    # TODO: ignore (or do something else) with system files.
    # A client (for example, vscode), if given a non-existent path to a file
    # (for example, where it was created), will try to open it and encounter an error.
    def get_stack_trace(self, thread_id: int) -> tuple[bool, str, list[dict]]:
        """
        Return the call stack for the specified thread.

        :param thread_id: ID of the thread to fetch the stack trace for.
        :return: A tuple containing success status, message, and stack frames.
        """
        self.send_command_and_get_result(f"-thread-select {thread_id}")
        responses = self.send_command_and_get_result("-stack-list-frames")

        if not responses:
            return False, "No response from GDB", []

        stack_frames = self._parse_stack_frames(responses)
        success, message = _is_gdb_response_successful(responses)
        return success, message, stack_frames

    def _extract_threads(self, responses: list[dict]) -> list[dict]:
        """Extract thread information from GDB responses."""
        for resp in responses:
            if resp.get(TYPE) == RESULT and resp.get(MESSAGE) == "done":
                return self._parse_threads(resp.get(PAYLOAD, {}).get("threads", []))
        return []

    def _parse_threads(self, threads: list[dict]) -> list[dict]:
        """Parse thread details from GDB payload."""
        keys = ["target-id", "name", "frame", "details", "state", "core"]
        return [
            {
                "id": int(thread[ID]),
                **{key: self._get_thread_value(thread, key) for key in keys},
            }
            for thread in threads
        ]

    def _get_thread_value(self, thread, key, default_prefix="Thread") -> dict:
        return thread.get(key, f"{default_prefix} {thread[ID]}")

    def _parse_stack_frames(self, responses: list[dict]) -> list[dict]:
        """
        Parse stack frames from GDB responses.

        :param responses: List of responses from GDB.
        :return: List of parsed stack frames.
        """
        for msg in responses:
            if msg.get(TYPE) == RESULT and msg.get(MESSAGE) == "done":
                payload = msg.get(PAYLOAD, {})
                gdb_stack = payload.get("stack", [])
                return [self._parse_frame(frame_info) for frame_info in gdb_stack]
        return []

    # TODO: Replace function name "??" for something more obvious, add arguments in parentheses
    def _parse_frame(self, frame_info: dict) -> dict:
        """
        Parse a single frame from GDB response.

        :param frame_info: Dictionary containing frame information.
        :return: A dictionary representing the parsed frame.
        """
        level = self._safe_int(frame_info.get("level"))
        line = self._safe_int(frame_info.get("line", "0"))
        return {
            "id": level,
            "name": frame_info.get("func", "<unknown>"),
            "source": {
                "name": frame_info.get("file", "<unknown>"),
                "path": frame_info.get("fullname", ""),
            },
            "line": line,
            "column": 0,  # GDB does not provide columns, the default is 0
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

    def _send_initial_commands(self):
        """Perform initial GDB setup."""
        self.send_command_and_get_result("-gdb-set mi-async on")
        self.send_command_and_get_result("-gdb-set confirm off")
        self.send_command_and_get_result("-enable-pretty-printing")
        self.send_command_and_get_result("set pagination off")
        self.send_command_and_get_result("set auto-solib-add on")
        print("GDB initialized and configured.", flush=True)

    def connect_to_gdbserver(self, gdb_server_address: str) -> tuple[bool, str]:
        """
        Connect to gdbserver at a given address.

        :param gdb_server_address: gdbserver address.
        """
        command = f"target extended-remote {gdb_server_address}"
        responses = self.send_command_and_get_result(command)
        success, message = _is_gdb_response_successful(responses)
        if success:
            responses = self.send_command_and_get_result("detach")
        return success, message

    def load_program_symbols(self, program_path: str):
        """Load the program symbols into the debugger."""
        if program_path:
            if not Path(program_path).exists():
                return False, f"The path {program_path} does not exist"
            command = f"file {program_path}"
            self.send_command_and_get_result(command)
        return True, ""


def _is_gdb_response_successful(responses: list[dict]) -> tuple[bool, str]:
    """
    Parse GDB responses for errors.

    :param responses: List of responses from GDB.
    :return: Tuple (success, error_message).
    """
    for resp in responses:
        if resp.get(TYPE) == RESULT and resp.get(MESSAGE) == "error":
            error_message = resp[PAYLOAD].get("msg", "Unknown error")
            return False, f"Error from GDB: {error_message}"
    return True, ""
