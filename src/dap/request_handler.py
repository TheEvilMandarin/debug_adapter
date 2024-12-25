from collections.abc import Iterator
from functools import wraps

from dap.dap_message import DAPEvent, DAPResponse
from gdb.backend import GDBBackend

ARGUMENTS = "arguments"
THREAD_ID = "threadId"


def register_command(name: str):
    """
    Register a method as a DAP command.

    :param name: The name of the command to register.
    :return: The decorated function with the `_dap_command` attribute.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        wrapper._dap_command = name  # noqa: WPS437
        return wrapper

    return decorator


class DAPRequestHandler:
    """Client request handler via Debug Adapter Protocol (DAP)."""

    def __init__(self, gdb_backend: GDBBackend):
        """
        Initialize the handler.

        :param gdb_backend: A GDBBackend instance to interact with GDB.
        """
        self.gdb_backend = gdb_backend
        self._commands = {}

        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if callable(attr) and hasattr(attr, "_dap_command"):
                self._commands[attr._dap_command] = attr  # noqa: WPS437

    def handle_request(self, request: dict) -> Iterator[dict]:
        """
        Process a client request and returns a response.

        :param request: JSON request from client.
        :return: JSON response for client.
        """
        command = request.get("command")
        print(f"Handling DAP command: {command}")

        if command in self._commands:
            yield from self._commands.get(command, self._unsupported_command)(request)
        else:
            yield from self._unsupported_command(request)

    @register_command("initialize")
    def _initialize(self, request: dict) -> Iterator[dict]:
        """Process the command `initialize`."""
        response = DAPResponse(
            request=request,
            command="initialize",

            # TODO: check the settings on the different gdb
            body={
                "SupportsConfigurationDoneRequest": True,
                "SupportsCompletionsRequest": False,  # TODO maybe someday (request completions)
                "SupportsEvaluateForHovers": True,  # TODO request evaluate
                "SupportsSetVariable": True,
                "SupportsFunctionBreakpoints": True,  # Check
                "SupportsConditionalBreakpoints": True,  # Check
                "SupportsDataBreakpoints": True,  # Check
                "SupportsClipboardContext": False,
                "SupportsLogPoints": False,
                "SupportsReadMemoryRequest": True,
                "SupportsModulesRequest": True,
                "SupportsGotoTargetsRequest": False,
                "SupportsDisassembleRequest": True,  # Check
                "SupportsValueFormattingOptions": True,
                "SupportsSteppingGranularity": True,
                "SupportsInstructionBreakpoints": True,  # Check
            },
        )
        yield response.to_dict()
        event = DAPEvent(event="initialize")
        yield event.to_dict()

    @register_command("attach")
    def _attach(self, request: dict) -> Iterator[dict]:
        """Process the command `attach`."""
        pid = request[ARGUMENTS].get("pid")
        print(f"Attaching to process with PID: {pid}")

        success, message = self.gdb_backend.attach_to_process(pid)

        response = DAPResponse(
            request=request,
            command="attach",
            success=success,
            message=message,
        )
        yield response.to_dict()

        # TODO: depending on the user's settings whether he wants to stop execution.
        event = DAPEvent(
            event="stopped",
            body={
                "reason": "entry",
                "allThreadsStopped": True,
            },
        )
        yield event.to_dict()

    @register_command("threads")
    def _threads(self, request: dict) -> Iterator[dict]:
        """Process the command `threads`."""
        success, message, threads = self.gdb_backend.get_threads()
        response = DAPResponse(
            request=request,
            command="threads",
            success=success,
            message=message,
            body={
                "threads": threads,
            },
        )
        yield response.to_dict()

    @register_command("stackTrace")
    def _stack_trace(self, request: dict) -> Iterator[dict]:
        """Process the command `stackTrace`."""
        response = DAPResponse(
            request=request,
            command="stackTrace",
        )

        thread_id = request[ARGUMENTS].get(THREAD_ID)
        if thread_id is None:
            response.success = False
            response.message = "'threadId' is required for stackTrace request"
            yield response.to_dict()

        success, message, stack_frames = self.gdb_backend.get_stack_trace(thread_id)
        response_body = {"stackFrames": stack_frames}
        response.success = success
        response.message = message
        response.body = response_body
        yield response.to_dict()

    @register_command("continue")
    def _continue(self, request: dict) -> Iterator[dict]:
        """Process the command `continue`."""
        thread_id = request[ARGUMENTS].get(THREAD_ID)

        success, message = self.gdb_backend.continue_execution(thread_id)
        response = DAPResponse(
            request=request,
            command="continue",
            success=success,
            message=message,
        )
        yield response.to_dict()

    @register_command("pause")
    def _pause(self, request: dict) -> Iterator[dict]:
        """Process the command `pause`."""
        thread_id = request[ARGUMENTS].get(THREAD_ID)

        success, message, gdb_response = self.gdb_backend.pause_execution(thread_id)
        response = DAPResponse(
            request=request,
            command="pause",
            success=success,
            message=message,
        )
        yield response.to_dict()
        event = DAPEvent(
            event="stopped",
            body={
                "reason": "pause",
                "threadId": gdb_response.get("thread-id"),
                "allThreadsStopped": gdb_response.get("stopped-threads") == "all",
            },
        )
        yield event.to_dict()

    @register_command("disconnect")
    def _disconnect(self, request: dict) -> Iterator[dict]:
        """Process the command `disconnect`."""
        self.gdb_backend.stop()
        response = DAPResponse(
            request=request,
            command="disconnect",
        )
        yield response.to_dict()

    def _unsupported_command(self, request: dict) -> Iterator[dict]:
        """Generate a response to an unsupported command."""
        command = request.get("command", "unknown")
        response = DAPResponse(
            request=request,
            success=False,
            command=command,
            message=f"Unsupported command: {command}",
        )
        yield response.to_dict()
