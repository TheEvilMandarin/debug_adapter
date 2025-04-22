"""Unit tests for BreakpointManager in GDB adapter."""

from unittest.mock import Mock

from src.gdb.breakpoints import BreakpointManager


def test_set_breakpoints(bp_manager: BreakpointManager, backend_mock: Mock):
    """Should correctly set multiple breakpoints in a given source file."""
    backend_mock.send_command_and_get_result.side_effect = [
        [{"type": "result", "message": "done"}],
        [{"type": "result", "message": "done"}],
    ]

    breakpoints = [{"line": 10}, {"line": 20}]
    success, msg, result = bp_manager.set_breakpoints("main.cpp", breakpoints)

    assert success is True
    assert msg == ""
    assert result == [
        {
            "verified": True,
            "line": 10,
            "source": {"path": "main.cpp"},
            "message": "",
        },
        {
            "verified": True,
            "line": 20,
            "source": {"path": "main.cpp"},
            "message": "",
        },
    ]


def test_clear_breakpoints(bp_manager: BreakpointManager, backend_mock):
    """Should remove all breakpoints from a given source file."""
    backend_mock.send_command_and_get_result.side_effect = [
        [  # -break-list
            {
                "type": "result",
                "message": "done",
                "payload": {
                    "BreakpointTable": {
                        "body": [
                            {"fullname": "main.cpp", "number": "1"},
                            {"fullname": "main.cpp", "number": "2"},
                        ],
                    },
                },
            },
        ],
        [{"type": "result", "message": "done"}],  # -break-delete 1
        [{"type": "result", "message": "done"}],  # -break-delete 2
    ]

    bp_manager.clear_breakpoints("main.cpp")

    backend_mock.send_command_and_get_result.assert_any_call("-break-list")
    backend_mock.send_command_and_get_result.assert_any_call("-break-delete 1")
    backend_mock.send_command_and_get_result.assert_any_call("-break-delete 2")
