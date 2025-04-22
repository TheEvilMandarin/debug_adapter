"""
Client request handler for the Debug Adapter Protocol (DAP).

This class is responsible for processing client requests received via the
Debug Adapter Protocol (DAP).
It translates these requests into appropriate commands for the GDB backend and manages the
interaction between the client and the debugger.
"""

import shlex
import subprocess  # nosec B404 # noqa: S404
from collections.abc import Iterator
from functools import wraps

from debug_adapter.common import (
    VAR_REF_LOCAL_BASE,
    VAR_REF_REGISTERS_BASE,
    CommandResult,
)
from debug_adapter.dap.dap_message import DAPEvent, DAPResponse
from debug_adapter.dap.notifier import DAPNotifier, NullNotifier
from debug_adapter.gdb.backend import GDBBackend

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

        wrapper._dap_command = name  # noqa: WPS437 # pylint: disable=W0212
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
        self._notifier: DAPNotifier = NullNotifier()
        self._commands = {}

        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if callable(attr) and hasattr(attr, "_dap_command"):
                self._commands[attr._dap_command] = attr  # noqa: WPS437

    @property
    def notifier(self) -> DAPNotifier:
        """Get the DAPNotifier."""
        return self._notifier

    @notifier.setter
    def notifier(self, value: DAPNotifier) -> None:
        """Set the DAPNotifier."""
        self._notifier = value
        self.gdb_backend.notifier = value

    def handle_request(self, request: dict) -> Iterator[dict]:
        """
        Process a client request and returns a response.

        :param request: JSON request from client.
        :return: JSON response for client.
        """
        command = request.get("command")
        print(f"Handling DAP command: {request}", flush=True)

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
                "SupportsEvaluateForHovers": False,  # TODO request evaluate
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
                "SupportsBreakpointLocationsRequest": True,
            },
        )
        yield response.to_dict()
        event = DAPEvent(event="initialized")
        yield event.to_dict()

    @register_command("configurationDone")
    def _configuration_done(self, request: dict) -> Iterator[dict]:
        """Process the command `configurationDone`."""
        response = DAPResponse(
            request=request,
            command="configurationDone",
            body={},
        )
        yield response.to_dict()

    def _set_custom_settings(self, request: dict) -> CommandResult:
        setup_commands = self._get_argument(request, "setupCommands", [])
        send_cmd = self.gdb_backend.send_command_and_check_for_success
        for command in setup_commands:
            command_text = command.get("text")

            if command_text:
                ignore_failures = command.get("ignoreFailures", False)
                result: CommandResult = send_cmd(command_text, ignore_failures)
                if not result.success:
                    return result

        gdb_server_address = self._get_argument(request, "gdbServer")
        if gdb_server_address:
            return self.gdb_backend.process_manager.connect_to_gdbserver(gdb_server_address)
        return CommandResult(success=True, message="")

    @register_command("attach")
    def _attach(self, request: dict) -> Iterator[dict]:
        """Process the command `attach`."""
        result: CommandResult = self._set_custom_settings(request)

        if result.success:
            pid = self._get_argument(request, "pid")
            print(f"Attaching to process with PID: {pid}")

            program_path = self._get_argument(request, "program")
            result = self.gdb_backend.process_manager.attach_to_process(pid, program_path)

        response = DAPResponse(
            request=request,
            command="attach",
            success=result.success,
            message=result.message,
        )
        yield response.to_dict()

        # TODO: depending on the user's settings whether he wants to stop execution.
        self.notifier.start_notifier()
        self.notifier.send_stopped_event(
            reason="entry",
            thread_id=1,
            all_threads_stopped=True,
            hit_breakpoint_ids=[],
        )

    @register_command("launch")
    def _launch(self, request: dict) -> Iterator[dict]:
        """Process the command launch."""
        result: CommandResult = self._set_custom_settings(request)
        spawner_pid = None
        if result.success:
            program_runner = self._get_argument(request, "programRunner")
            if program_runner:
                result, spawner_pid = self._launch_via_runner(request, program_runner)
            else:
                result, spawner_pid = self._launch_by_default(request)

        response = DAPResponse(
            request=request,
            command="launch",
            success=result.success,
            message=result.message,
            body={
                "spawnerPid": spawner_pid,
            },
        )
        yield response.to_dict()

    def _launch_via_runner(
        self,
        request: dict,
        program_runner: str,
    ) -> tuple[CommandResult, int | None]:
        """
        Launch the application via programRunner.

        If programRunner is specified, processSpawner is also required to find the spawner process.
        Spawner - a process that itself spawns new processes.
        If the process search is successful, attach occurs, the bash process for the runner
        is launched, and further actions are taken.
        """
        process_spawner = self._get_argument(request, "processSpawner")
        if not process_spawner:
            return CommandResult(
                success=False,
                message="processSpawner not specified",
            ), None
        spawner_pid = self.gdb_backend.process_manager.get_pid_by_name(process_spawner)
        if not spawner_pid:
            return CommandResult(
                success=False,
                message=f"Unable to find the process {process_spawner}",
            ), None

        result: CommandResult = self.gdb_backend.process_manager.attach_to_process(spawner_pid)
        self.gdb_backend.breakpoint_manager.set_exec_catchpoint()
        self.gdb_backend.execution_manager.continue_execution()
        self.notifier.start_notifier()
        with subprocess.Popen(  # noqa: S603
            [
                "/bin/bash",
                program_runner,
            ],
        ) as bash_process:  # nosec B603
            bash_process.wait()
        return result, spawner_pid

    def _launch_by_default(self, request: dict) -> tuple[CommandResult, int | None]:
        """
        Launch the application by default.

        Loading symbols from executable file, setting arguments,
        launching the application and calling pause_execution after startup.
        """
        program_path = self._get_argument(request, "program")
        program_args = self._get_argument(request, "args") or []
        result: CommandResult = self.gdb_backend.execution_manager.load_executable_and_symbols(
            program_path,
        )
        if not result.success:
            return result, None

        arg_string = ""
        if program_args:
            quoted_args = [shlex.quote(arg) for arg in program_args]
            arg_string = " ".join(quoted_args)

        self.gdb_backend.execution_manager.set_program_arguments(arg_string)
        result = self.gdb_backend.breakpoint_manager.set_breakpoint_on_main()
        self.notifier.start_notifier()
        self.gdb_backend.execution_manager.exec_run()

        return CommandResult(success=True, message=""), None

    @register_command("handleNewProcess")
    def _handle_new_process(self, request: dict) -> Iterator[dict]:
        """Process the command `handleNewProcess`."""
        program_runner = self._get_argument(request, "spawnerPid")
        program_path = self._get_argument(request, "program")
        self.gdb_backend.process_manager.detach_inferiors_with_pids([program_runner])
        result: CommandResult = self.gdb_backend.process_manager.load_program_symbols(program_path)
        processes: list = []
        if result.success:
            result = self.gdb_backend.breakpoint_manager.set_breakpoint_on_main()
        if result.success:
            result, processes = self.gdb_backend.process_manager.get_processes()
        current_pid = self.gdb_backend.process_manager.get_current_pid()

        response = DAPResponse(
            request=request,
            command="handleNewProcess",
            success=result.success,
            message=result.message,
            body={"processes": processes, "currentProcess": current_pid},
        )
        yield response.to_dict()
        self.gdb_backend.execution_manager.continue_execution()

    @register_command("listProcesses")
    def _list_processes(self, request: dict) -> Iterator[dict]:
        """Process the command `listProcesses`."""
        result, processes = self.gdb_backend.process_manager.get_processes()
        current_pid = self.gdb_backend.process_manager.get_current_pid()

        response = DAPResponse(
            request=request,
            command="listProcesses",
            success=result.success,
            message=result.message,
            body={"processes": processes, "currentProcess": current_pid},
        )
        yield response.to_dict()

    @register_command("addInferiors")
    def _add_inferiors(self, request: dict) -> Iterator[dict]:
        """Process the command `addInferiors`."""
        pids = self._get_argument(request, "pids", [])
        # When adding inferiors, gdb briefly starts and stops the program being debugged.
        # The client does not need to know about this
        with self.notifier.suspend():
            self.gdb_backend.process_manager.add_inferior_with_pids(pids)

        response = {
            "type": "response",
            "request_seq": request.get("seq", 0),
            "command": "addInferiors",
            "success": True,
            "message": "",
            "body": {},
        }
        yield response

    @register_command("detachInferiors")
    def _detach_inferiors(self, request: dict):
        """Process the command `detachInferiors`."""
        pids = self._get_argument(request, "pids", [])
        self.gdb_backend.process_manager.detach_inferiors_with_pids(pids)
        current_pid = self.gdb_backend.process_manager.get_current_pid()

        # Send events to update the client's state
        self.notifier.send_continued_event(thread_id="1", all_threads_continued=True)
        self.notifier.send_stopped_event(
            reason="detach inferior",
            thread_id=1,
            all_threads_stopped=True,
            hit_breakpoint_ids=[],
        )

        response = {
            "type": "response",
            "request_seq": request.get("seq", 0),
            "command": "detachInferiors",
            "success": True,
            "message": "",
            "body": {"processes": current_pid, "newCurrentPid": current_pid},
        }

        yield response

    @register_command("selectInferior")
    def _select_inferior(self, request: dict):
        """Process the command `selectInferior`."""
        pid = self._get_argument(request, "pid")

        success = self.gdb_backend.process_manager.select_inferior_by_pid(pid)

        response = {
            "type": "response",
            "request_seq": request.get("seq", 0),
            "command": "selectInferior",
            "success": success,
            "message": "Switched to inferior"
            if success
            else f"Failed to switch to inferior for PID {pid}",
            "body": {},
        }

        yield response

    @register_command("evaluate")
    def _evaluate(self, request: dict):
        """Process the command `evaluate`."""
        expression = self._get_argument(request, "expression", "")

        responses = self.gdb_backend.send_command_and_get_result(expression)

        response = {
            "type": "response",
            "request_seq": request.get("seq", 0),
            "command": "evaluate",
            "success": True,
            "body": {"result": responses},
        }

        yield response

    @register_command("continueAfterProcessExit")
    def _continue_after_process_exit(self, request: dict):
        continue_debugging = False
        if self.gdb_backend.process_manager.get_inferiors_list():
            continue_debugging = True
            self.gdb_backend.process_manager.get_current_inferior()
            # Refresh gdb and client state
            self.gdb_backend.execution_manager.continue_execution()
            self.gdb_backend.execution_manager.pause_execution()
        response = DAPResponse(
            request=request,
            command="continueAfterProcessExit",
            body={
                "continue": continue_debugging,
            },
        )
        yield response.to_dict()

    @register_command("threads")
    def _threads(self, request: dict) -> Iterator[dict]:
        """Process the command `threads`."""
        success, message, threads = self.gdb_backend.thread_manager.get_threads()
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

    @register_command("stackTrace")  # TODO: With startFrame and levels
    def _stack_trace(self, request: dict) -> Iterator[dict]:
        """Process the command `stackTrace`."""
        response = DAPResponse(
            request=request,
            command="stackTrace",
        )

        thread_id = self._get_argument(request, THREAD_ID)
        if thread_id is None:
            response.success = False
            response.message = "'threadId' is required for stackTrace request"
            yield response.to_dict()

        success, message, stack_frames = self.gdb_backend.stack_trace_manager.get_stack_trace(
            thread_id,
        )
        response_body = {"stackFrames": stack_frames}
        response.success = success
        response.message = message
        response.body = response_body
        yield response.to_dict()

    @register_command("continue")
    def _continue(self, request: dict) -> Iterator[dict]:
        """Process the command `continue`."""
        thread_id = self._get_argument(request, THREAD_ID)

        result: CommandResult = self.gdb_backend.execution_manager.continue_execution(thread_id)

        response = DAPResponse(
            request=request,
            command="continue",
            success=result.success,
            message=result.message,
        )
        yield response.to_dict()

    @register_command("pause")
    def _pause(self, request: dict) -> Iterator[dict]:
        """Process the command `pause`."""
        thread_id = self._get_argument(request, THREAD_ID)

        result: CommandResult = self.gdb_backend.execution_manager.pause_execution(thread_id)

        response = DAPResponse(
            request=request,
            command="pause",
            success=result.success,
            message=result.message,
        )
        yield response.to_dict()

    @register_command("disconnect")
    def _disconnect(self, request: dict) -> Iterator[dict]:
        """Process the command `disconnect`."""
        self.gdb_backend.stop()
        response = DAPResponse(
            request=request,
            command="disconnect",
        )
        yield response.to_dict()

    @register_command("source")
    def _source(self, request: dict) -> Iterator[dict]:
        """Process the command `source`."""
        response = DAPResponse(
            request=request,
            command="source",
        )

        arguments = request.get(ARGUMENTS, {})
        source = arguments.get("source", {})
        source_path = source.get("path")

        if not source_path:
            response.success = False
            response.message = "The 'path' field is required in the 'source' object."
            yield response.to_dict()
            return

        # Attempt to read the source file
        try:
            with open(source_path, encoding="utf-8") as source_file:
                source_content = source_file.read()

            response.success = True
            response.body = {
                "content": source_content,
            }
        except FileNotFoundError:
            response.success = False
            response.message = f"Source file not found: {source_path}"
        except OSError as err:
            response.success = False
            response.message = f"Error reading source file: {err}"

        yield response.to_dict()

    @register_command("scopes")
    def _scopes(self, request: dict) -> Iterator[dict]:
        """Process the command `scopes`."""
        response = DAPResponse(
            request=request,
            command="scopes",
        )

        arguments = request.get(ARGUMENTS, {})
        frame_id = arguments.get("frameId")

        if frame_id is None:
            response.success = False
            response.message = "The 'frameId' field is required in the arguments."
            yield response.to_dict()
            return

        result: CommandResult = self.gdb_backend.select_frame(frame_id)
        response.success = result.success
        response.message = result.message
        if not response.success:
            yield response.to_dict()
            return

        locals_scope = {
            "name": "Locals",
            "variablesReference": VAR_REF_LOCAL_BASE + frame_id,
            "expensive": False,
        }

        registers_scope = {
            "name": "Registers",
            "variablesReference": VAR_REF_REGISTERS_BASE + frame_id,
            "expensive": False,
        }

        scopes = []
        if self.gdb_backend.variable_manager.check_for_local_variables():
            scopes.append(locals_scope)

        if self.gdb_backend.variable_manager.check_for_registers():
            scopes.append(registers_scope)

        response.success = True
        response.body = {
            "scopes": scopes,
        }

        yield response.to_dict()

    @register_command("variables")
    def _variables(self, request: dict) -> Iterator[dict]:
        """Process the `variables` request."""
        response = DAPResponse(
            request=request,
            command="variables",
        )

        arguments = request.get(ARGUMENTS, {})
        variables_reference = arguments.get("variablesReference")

        if variables_reference is None:
            response.success = False
            response.message = "The 'variablesReference' field is required."
            yield response.to_dict()
            return

        try:
            variables = self.gdb_backend.variable_manager.get_vars(variables_reference)

            response.success = True
            response.body = {
                "variables": [
                    {
                        "name": var["name"],
                        "value": var.get("value", "<unknown>"),
                        "variablesReference": var["variablesReference"],
                    }
                    for var in variables
                ],
            }
        except (RuntimeError, KeyError, ValueError, TypeError, AttributeError) as err:
            response.success = False
            response.message = f"Failed to fetch variables: {err}"

        yield response.to_dict()

    @register_command("breakpointLocations")
    def _breakpoint_locations(self, request: dict) -> Iterator[dict]:
        """Process the `breakpointLocations` command, returning possible breakpoints."""
        arguments = request.get("arguments", {})
        source_path = arguments.get("source", {}).get("path", "")
        line = arguments.get("line")
        end_line = arguments.get("endLine")

        if not source_path or line is None:
            response = DAPResponse(
                request=request,
                command="breakpointLocations",
                success=False,
                message="Invalid arguments: source path and line are required.",
            )
            yield response.to_dict()
            return

        success, message, locations = self.gdb_backend.breakpoint_manager.get_breakpoint_locations(
            source_path,
            line,
            end_line,
        )

        response = DAPResponse(
            request=request,
            command="breakpointLocations",
            success=success,
            message=message,
            body={"breakpoints": locations},
        )
        yield response.to_dict()

    @register_command("setBreakpoints")
    def _set_breakpoints(self, request: dict) -> Iterator[dict]:
        """Process the `setBreakpoints` command, setting breakpoints in GDB."""
        arguments = request.get("arguments", {})
        source_path = arguments.get("source", {}).get("path", "")
        breakpoints = arguments.get("breakpoints", [])

        if not source_path:
            response = DAPResponse(
                request=request,
                command="setBreakpoints",
                success=False,
                message="Invalid arguments: source path is required.",
            )
            yield response.to_dict()
            return

        self.gdb_backend.breakpoint_manager.clear_breakpoints(source_path)

        result_breakpoints: list = []
        message = ""
        success = True

        if breakpoints:
            success, message, result_breakpoints = (
                self.gdb_backend.breakpoint_manager.set_breakpoints(
                    source_path,
                    breakpoints,
                )
            )

        response = DAPResponse(
            request=request,
            command="setBreakpoints",
            success=success,
            message=message,
            body={"breakpoints": result_breakpoints},
        )
        yield response.to_dict()

    @register_command("next")
    def _next(self, request: dict) -> Iterator[dict]:
        """Process the command `next`."""
        thread_id = self._get_argument(request, THREAD_ID)

        response = DAPResponse(
            request=request,
            command="next",
            success=True,
            message="",
        )

        result: CommandResult = self.gdb_backend.execution_manager.execute_next(thread_id)

        if not result.success:
            response.success = False
            response.message = result.message
        yield response.to_dict()

    @register_command("stepIn")
    def _step_in(self, request: dict) -> Iterator[dict]:
        """Process the command `stepIn`."""
        thread_id = self._get_argument(request, THREAD_ID)

        response = DAPResponse(
            request=request,
            command="stepIn",
            success=True,
            message="",
        )

        result: CommandResult = self.gdb_backend.execution_manager.execute_step_in(thread_id)

        if not result.success:
            response.success = False
            response.message = result.message
        yield response.to_dict()

    @register_command("stepOut")
    def _step_out(self, request: dict) -> Iterator[dict]:
        """Process the command `stepOut`."""
        thread_id = self._get_argument(request, self._get_argument(request, "pid"), None)
        single_thread_default = False
        single_thread = self._get_argument(request, "singleThread", single_thread_default)

        response = DAPResponse(
            request=request,
            command="stepOut",
            success=True,
            message="",
        )

        result: CommandResult = self.gdb_backend.execution_manager.execute_step_out(
            thread_id,
            single_thread,
        )

        if not result.success:
            response.success = False
            response.message = result.message
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

    def _get_argument(self, request: dict, key: str, default=None):
        """
        Retrieve the argument from request[ARGUMENTS].

        :param request: DAP input request.
        :param key: The key of the argument.
        :param default: Default value if the key is missing.
        :return: Argument value or default.
        """
        return request.get(ARGUMENTS, {}).get(key, default)
