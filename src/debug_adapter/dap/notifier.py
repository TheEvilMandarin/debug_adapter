"""
DAPNotifier module: Event notification mechanism for the Debug Adapter Protocol (DAP).

This module provides functionality for sending events from the debugger backend to the DAP client.
It is responsible for creating and dispatching various DAP events, such as "stopped", "continued",
and "invalidated", to notify the client about changes in the debugger's state.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from debug_adapter.dap.server import DAPServer

import json

from debug_adapter.dap.dap_message import DAPEvent


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
            self.server.client_conn.sendall((header + event_json).encode())
            print(f"Sent event: {event}", flush=True)
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

    @contextmanager
    def suspend(self):
        """Context manager that temporarily disables event notifications."""
        self.stop_notifier()
        try:
            yield
        finally:
            self.start_notifier()


class NullNotifier(DAPNotifier):
    """
    A no-operation (no-op) notifier that implements the same interface as DAPNotifier.

    This class can be used as a drop-in replacement for DAPNotifier when actual event sending
    is not desired or available. All methods are implemented as no-ops.
    """

    def __init__(self, *_):
        """
        Initialize the NullNotifier.

        This constructor accepts any arguments, but ignores them because no initialization
        is necessary for a no-op notifier.
        """
        super().__init__(server=None)

    def send_event(self, event: dict):
        """
        No-op implementation of send_event.

        This method intentionally does nothing and ignores the 'event' parameter.

        :param event: A dictionary representing the event to be sent.
        """

    def send_stopped_event(self, *args, **kwargs):
        """
        No-op implementation of send_stopped_event.

        Ignores any positional or keyword arguments that would normally be used
        to create and send a 'stopped' event.
        """

    def send_continued_event(self, *args, **kwargs):
        """
        No-op implementation of send_continued_event.

        This method ignores arguments provided for a 'continued' event.
        """

    def send_invalidated_event(self, *args, **kwargs):
        """
        No-op implementation of send_invalidated_event.

        This method ignores any input related to invalidated areas.
        """

    def send_new_process_event(self):
        """
        No-op implementation of send_new_process_event.

        This method does not perform any action for a new process event.
        """

    def send_exited_process_event(self):
        """
        No-op implementation of send_exited_process_event.

        This method does not perform any action for an exited process event.
        """

    def stop_notifier(self):
        """
        No-op implementation of stop_notifier.

        This method does nothing; it is provided to adhere to the interface.
        """

    def start_notifier(self):
        """
        No-op implementation of start_notifier.

        This method does nothing; it is provided to adhere to the interface.
        """

    @contextmanager
    def suspend(self):
        """
        No-op context manager that does not change any state.

        This context manager yields control immediately and performs no actions
        upon entering or exiting the context.
        """
        yield
