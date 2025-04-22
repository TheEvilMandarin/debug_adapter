"""
This module serves as a shared utility for both the backend
and server components of the Debug Adapter Protocol (DAP) implementation.

It includes common data structures, constants, and utilities that are used
across different parts of the system.
"""

from collections import namedtuple

CommandResult = namedtuple("CommandResult", ["success", "message"])


# Constants for `variablesReference`
VAR_REF_LOCAL_BASE = 100000  # Local variables
VAR_REF_REGISTERS_BASE = 200000  # Registers
VAR_REF_DYNAMIC_BASE = 300000  # Dynamic objects (std::vector, struct, arrays)
