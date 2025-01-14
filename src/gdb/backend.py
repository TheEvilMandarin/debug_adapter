from pygdbmi.gdbcontroller import DEFAULT_GDB_TIMEOUT_SEC, GdbController

TYPE = "type"
MESSAGE = "message"
PAYLOAD = "payload"
ID = "id"


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

    def send_command(
        self,
        command: str,
        timeout: int = DEFAULT_GDB_TIMEOUT_SEC,
    ) -> list[dict]:
        """
        Send a command to GDB and returns a response.

        :param command: GDB command (e.g. `-exec-continue`).
        :param timeout: Response timeout (in seconds).
        :return: Reply from GDB.
        """
        responses = []
        if self.gdbmi:
            print(f"Sending command to gdb: {command}", flush=True)
            responses = self.gdbmi.write(command, timeout_sec=timeout)
            print(f"Response from gdb: {responses}", flush=True)
        return responses

    def attach_to_process(self, pid: int) -> tuple[bool, str]:
        """Connect to a process by its PID."""
        responses = self.send_command(f"attach {pid}")
        return _is_gdb_response_successful(responses)

    # TODO: get more correct names of threads.
    # Now the thread name is returned as the actual thread name.
    # Think about how to return it more correctly:
    # (for example, the name of the program being launched + the name of the thread).
    def get_threads(self) -> tuple[bool, str, list[dict]]:
        """Return a list of threads managed by GDB."""
        responses = self.send_command("-thread-info")

        success, error_message = _is_gdb_response_successful(responses)
        threads = self._extract_threads(responses) if success else []
        return success, error_message, threads

    def continue_execution(self, thread_id: int | None = None) -> tuple[bool, str]:
        """Continue program execution."""
        command = (
            f"-exec-continue --thread {thread_id}" if thread_id else "-exec-continue"
        )
        responses = self.send_command(command)
        return _is_gdb_response_successful(responses)

    def pause_execution(
        self,
        thread_id: int | None = None,
    ) -> tuple[bool, str, dict]:
        """Pause program execution."""
        if thread_id:
            self.send_command(f"-thread-select {thread_id}")
        responses = self.send_command("-exec-interrupt")

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
        self.send_command(f"-thread-select {thread_id}")
        responses = self.send_command("-stack-list-frames")

        if not responses:
            return False, "No response from GDB", []

        stack_frames = self._parse_stack_frames(responses)
        success, message = _is_gdb_response_successful(responses)
        return success, message, stack_frames

    def _extract_threads(self, responses: list[dict]) -> list[dict]:
        """Extract thread information from GDB responses."""
        for resp in responses:
            if resp.get(TYPE) == "result" and resp.get(MESSAGE) == "done":
                return self._parse_threads(resp.get(PAYLOAD, {}).get("threads", []))
        return []

    def _parse_threads(self, threads: list[dict]) -> list[dict]:
        """Parse thread details from GDB payload."""
        return [
            {
                "id": int(thread[ID]),
                "name": thread.get("target-id", f"Thread {thread[ID]}"),
            }
            for thread in threads
        ]

    def _parse_stack_frames(self, responses: list[dict]) -> list[dict]:
        """
        Parse stack frames from GDB responses.

        :param responses: List of responses from GDB.
        :return: List of parsed stack frames.
        """
        for msg in responses:
            if msg.get(TYPE) == "result" and msg.get(MESSAGE) == "done":
                payload = msg.get(PAYLOAD, {})
                gdb_stack = payload.get("stack", [])
                return [self._parse_frame(frame_info) for frame_info in gdb_stack]
        return []

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
        self.send_command("-gdb-set mi-async on")
        self.send_command("-enable-pretty-printing")
        self.send_command("set pagination off")
        self.send_command("set auto-solib-add on")
        print("GDB initialized and configured.", flush=True)


def _is_gdb_response_successful(responses: list[dict]) -> tuple[bool, str]:
    """
    Parse GDB responses for errors.

    :param responses: List of responses from GDB.
    :return: Tuple (success, error_message).
    """
    for resp in responses:
        if resp.get(TYPE) == "result" and resp.get(MESSAGE) == "error":
            error_message = resp[PAYLOAD].get("msg", "Unknown error")
            return False, f"Error from GDB: {error_message}"
    return True, ""
