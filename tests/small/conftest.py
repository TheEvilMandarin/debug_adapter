"""Shared pytest fixtures for GDB adapter tests."""

from unittest.mock import Mock

import pytest

from src.gdb.backend import GDBBackend
from src.gdb.breakpoints import BreakpointManager
from src.gdb.variables import VariableManager


@pytest.fixture
def backend_mock() -> Mock:
    """Provide a mock instance of the GDBBackend interface."""
    return Mock(spec=GDBBackend)


@pytest.fixture
def variable_manager(backend_mock: GDBBackend):  # noqa: WPS442
    """Provide a VariableManager instance using a mocked backend."""
    return VariableManager(backend=backend_mock)


@pytest.fixture
def bp_manager(backend_mock: Mock):  # noqa: WPS442
    """Provide a BreakpointManager instance using a mocked backend."""
    return BreakpointManager(backend=backend_mock)
