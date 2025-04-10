"""
DAPNotifier module: Event notification mechanism for the Debug Adapter Protocol (DAP).

This module provides functionality for sending events from the debugger backend to the DAP client.
It is responsible for creating and dispatching various DAP events, such as "stopped", "continued",
and "invalidated", to notify the client about changes in the debugger's state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dap.server import DAPServer

import json

from dap.dap_message import DAPEvent


class DAPNotifier:
    """Class for sending events to a DAP client via the server."""

    def __init__(self, server: DAPServer):
        """
        Initialize the DAPNotifier.
        :param server: The `DAPServer` instance that contains the connection to the client.
        """
        self.server = server
        self.notifier_is_active = False

    def send_event(self, event: dict):
        """
        Send a DAP event to the client.

        :param event: JSON event object.
        """
        if not self.server.client_conn:
            print("No client connection. Cannot send event.", flush=True)
            return

        event_json = json.dumps(event)
        content_length = len(event_json.encode())
        header = f"Content-Length: {content_length}\r\n\r\n"

        if self.notifier_is_active:
            try:
                self.server.client_conn.sendall((header + event_json).encode())
                print(f"Sent event: {event}", flush=True)
            except Exception as ex:
                print(f"Failed to send event: {ex}\n.Content of event: {event}", flush=True)
        else:
            print(
                f"Unable to send event: notifier is not active. Content of event: {event}",
                flush=True,
            )

    def send_stopped_event(
        self,
        reason: str,
        thread_id: int,
        all_threads_stopped: bool,
        hit_breakpoint_ids: list[int],
    ):
        """
        Create and dispatches a 'stopped' event.

        :param reason: Reason for stopping (for example, "breakpoint", "step").
        :param thread_id: ID of the thread that stopped.
        :param all_threads_stopped: Whether all threads are stopped.
        :param hit_breakpoint_ids: List of breakpoint IDs that were hit.
        """
        event = DAPEvent(
            event="stopped",
            body={
                "reason": reason,
                "threadId": thread_id,
                "allThreadsStopped": all_threads_stopped,
                "hitBreakpointIds": hit_breakpoint_ids,
            },
        )
        self.send_event(event.to_dict())

    def send_continued_event(
        self,
        thread_id: str,
        all_threads_continued: bool,
    ):
        """
        Create and dispatches the 'continued' event.

        :param thread_id: ID of the thread that continued execution.
        :param all_threads_continued: Whether all threads are continued.
        """
        event = DAPEvent(
            event="continued",
            body={
                "threadId": thread_id,
                "allThreadsContinued": all_threads_continued,
            },
        )
        self.send_event(event.to_dict())

    def send_invalidated_event(self, areas: list[str]):
        """
        Create and dispatches the 'invalidated' event.

        :param areas: List of areas that have been invalidated (eg "stacks").
        """
        event = DAPEvent(
            event="invalidated",
            body={
                "areas": areas,
            },
        )
        self.send_event(event.to_dict())

    def send_new_process_event(self):
        """Create and dispatches the 'exec-new' event."""
        # We do not pass the process number, because it will be automatically added
        # to the list of inferiors when updating the ui. If this is a process that
        # was created during the launch request (which is most likely), in post-processing
        # we will disconnect from the spawner process and switch to the only available inferior
        # (the new process we need).
        event = DAPEvent(event="newProcess")
        self.send_event(event.to_dict())

    def send_exited_process_event(self):
        """Create and dispatches the 'exited' event."""
        event = DAPEvent(event="exitedProcess")
        self.send_event(event.to_dict())

    def stop_notifier(self):
        """Deactivate the notifier to prevent sending events to the client."""
        self.notifier_is_active = False

    def start_notifier(self):
        """Activate the notifier to allow sending events to the client."""
        self.notifier_is_active = True
