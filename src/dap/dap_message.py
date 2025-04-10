"""
Module for generating responses and events in the Debug Adapter Protocol (DAP).

This module provides classes for creating standardized responses and events
that adhere to the Debug Adapter Protocol (DAP) specification. These classes
are used to communicate between the debug adapter and the client (e.g., an IDE
like VS Code) during a debugging session.
"""


class DAPResponse:
    """
    A unified class for generating DAP responses.

    This class represents a response in the Debug Adapter Protocol (DAP).
    """

    def __init__(
        self,
        request: dict,
        command: str,
        success: bool = True,
        body: dict | None = None,
        message: str = "",
    ):  # pylint: disable=too-many-arguments too-many-positional-arguments
        """
        Initialize a DAPResponse object.

        :param request: JSON client request containing a sequence number.
        :param command: The name of the command associated with this response.
        :param success: Indicates whether the command was successful (default: True).
        :param body: Response body as a dictionary (default: None).
        :param message: Error message if the response is unsuccessful (default: empty string).
        """
        self.type = "response"
        self.request_seq = request.get("seq")
        self.command = command
        self.success = success
        self.body = body or {}
        self.message = message

    def to_dict(self) -> dict:
        """
        Convert the DAPResponse object to a dictionary.

        :return: A dictionary representation of the response.
        """
        return {
            "type": self.type,
            "request_seq": self.request_seq,
            "success": self.success,
            "command": self.command,
            "body": self.body,
            "message": self.message,
        }


class DAPEvent:
    """
    A unified class for generating DAP events.

    This class represents an event in the Debug Adapter Protocol (DAP).
    """

    def __init__(self, event: str, body: dict | None = None):
        """
        Initialize a DAPEvent object.

        :param event: Name of the event.
        :param body: Event body as a dictionary (default: None).
        """
        self.type = "event"
        self.event = event
        self.body = body or {}

    def to_dict(self) -> dict:
        """
        Convert the DAPEvent object to a dictionary.

        :return: A dictionary representation of the event.
        """
        return {
            "type": self.type,
            "event": self.event,
            "body": self.body,
        }
