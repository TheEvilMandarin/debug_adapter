"""
Module for managing variables in GDB.

This module provides functionality for fetching local variables, registers,
and variable children, as well as handling GDB's variable objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gdb.backend import GDBBackend

from common import VAR_REF_DYNAMIC_BASE, VAR_REF_LOCAL_BASE, VAR_REF_REGISTERS_BASE

VAR_REF_NO_NESTING = 0


class VariableManager:
    """
    Manages variables in a debugging session using GDB.

    This class provides methods for retrieving local variables,
    registers, and handling structured data like arrays and objects.
    """

    def __init__(self, backend: GDBBackend):
        """
        Initialize the VariableManager.

        :param backend: An instance of GDBBackend for executing GDB commands.
        """
        self.backend: GDBBackend = backend
        self._var_map: dict = {}  # Stores the variablesReference -> GDB object relationships
        self._var_ref_dynamic_counter: int = VAR_REF_DYNAMIC_BASE

    def get_vars(self, var_ref: int) -> list[dict]:
        """
        Retrieve a list of variables based on `variablesReference`.

        :param var_ref: Reference ID for variables.
        :return: List of variables.
        """
        if VAR_REF_LOCAL_BASE <= var_ref < VAR_REF_REGISTERS_BASE:
            return self._get_local_vars()

        if VAR_REF_REGISTERS_BASE <= var_ref < VAR_REF_DYNAMIC_BASE:
            return self.get_registers()

        return self.get_variable_children(var_ref)

    def _get_local_vars(self) -> list[dict]:
        """
        Fetch and parse local variables from GDB.

        :return: List of parsed local variables.
        """
        local_variables = self.get_local_variables_with_values()

        parsed_vars = []
        for var in local_variables:
            var_name = var["name"]
            value = var.get("value", "<unknown>")

            # If the variable is complex, create it in GDB using -var-create
            var_ref = (
                self.create_gdb_variable(var_name)["variablesReference"]
                if self._is_complex_variable(value)
                else VAR_REF_NO_NESTING
            )

            parsed_vars.append(
                {
                    "name": var_name,
                    "value": value,
                    "variablesReference": var_ref,
                },
            )

        return parsed_vars

    def get_local_variable_names(self) -> list[str]:
        """
        Fetch only the names of local variables for the current frame from GDB.

        :return: List of variable names.
        """
        responses = self.backend.send_command_and_get_result("-stack-list-locals 0")

        if not responses:
            return []

        for resp in responses:
            if resp.get("type") == "result" and resp.get("message") == "done":
                locals_list = resp.get("payload", {}).get("locals", [])
                return [var for var in locals_list if isinstance(var, str)]

        return []

    def get_registers_names(self) -> list[str]:
        """
        Fetch only the names of registers for the current frame from GDB.

        :return: List of variable names.
        """
        responses = self.backend.send_command_and_get_result("-data-list-register-names")

        if not responses:
            return []

        for resp in responses:
            if resp.get("type") == "result" and resp.get("message") == "done":
                locals_list = resp.get("payload", {}).get("register-names", [])
                return [var for var in locals_list if isinstance(var, str)]

        return []

    def get_local_variables_with_values(self) -> list[dict]:
        """
        Fetch local variables with their values for the current frame from GDB.

        :return: List of dictionaries containing variable names and values.
        """
        responses = self.backend.send_command_and_get_result("-stack-list-locals 1")

        if not responses:
            return []

        for resp in responses:
            if resp.get("type") == "result" and resp.get("message") == "done":
                locals_list = resp.get("payload", {}).get("locals", [])
                return [var for var in locals_list if isinstance(var, dict)]

        return []

    def get_registers(self) -> list:  # TODO
        """
        Fetch registers for the current frame from GDB.
        Not implemented yet.
        """
        return []

    def create_gdb_variable(self, var_name: str) -> dict:
        """
        Create a GDB variable object.

        :param var_name: Name of the variable in GDB.
        :return: Dictionary containing variable information.
        """
        hash_var_name = {hash(var_name)}
        gdb_var_name = f"var_{hash_var_name}"
        self.safe_var_delete(gdb_var_name)
        cmd = f"-var-create - * {var_name}"
        responses = self.backend.send_command_and_get_result(cmd)

        return self._extract_variable_from_response(responses, var_name)

    def _extract_variable_from_response(self, responses: list[dict], var_name: str) -> dict:
        """
        Extract variable details from GDB responses.

        :param responses: List of responses from GDB.
        :param var_name: Name of the variable.
        :return: Dictionary with variable details.
        """
        payload = self._parse_gdb_response(responses)
        return self._extract_variable_from_payload(payload, var_name) if payload else {}

    def _parse_gdb_response(self, responses: list[dict]) -> dict | None:
        """
        Parse GDB responses and extract the payload if available.

        :param responses: List of responses from GDB.
        :return: Parsed payload or None if no valid response.
        """
        for resp in responses:
            if resp.get("type") == "result" and resp.get("message") == "done":
                return resp.get("payload", {})
        return None

    def _extract_variable_from_payload(self, payload: dict, var_name: str) -> dict:
        """
        Extract variable details from a GDB response payload.

        :param payload: GDB response payload.
        :param var_name: Name of the variable.
        :return: Dictionary with variable details.
        """
        numchild = int(payload.get("numchild", "0"))
        has_more = payload.get("has_more", "0")
        displayhint = payload.get("displayhint", "")

        can_expand = numchild > 0 or has_more == "1" or displayhint == "array"
        gdb_var_name = payload.get("name", "")

        if can_expand and gdb_var_name:
            var_ref = self._generate_new_var_dynamic_ref()
            self._var_map[var_ref] = gdb_var_name

        return {
            "name": var_name,
            "value": payload.get("value", "<unknown>"),
            "type": payload.get("type", "unknown"),
            "numchild": numchild,
            "variablesReference": var_ref,
        }

    def _generate_new_var_dynamic_ref(self) -> int:
        """
        Generate a new unique variablesReference for dynamic variable.

        :return: New unique reference ID.
        """
        ref = self._var_ref_dynamic_counter
        self._var_ref_dynamic_counter += 1
        return ref

    def safe_var_delete(self, gdb_name: str):
        """
        Delete a GDB variable safely.

        :param gdb_name: Name of the variable in GDB.
        """
        cmd = f"-var-delete {gdb_name}"
        self.backend.send_command_and_get_result(cmd)

    def get_variable_children(self, var_ref: int) -> list[dict]:
        """
        Retrieve child variables of a given GDB variable.

        :param var_ref: Reference ID of the parent variable.
        :return: List of child variables.
        """
        gdb_var_name = self._var_map.get(var_ref)
        if not gdb_var_name:
            return []

        cmd_children = f"-var-list-children --all-values {gdb_var_name} 0 1000"
        responses = self.backend.send_command_and_get_result(cmd_children)

        return self._extract_variable_children_from_response(responses, gdb_var_name)

    def _extract_variable_children_from_response(
        self,
        responses: list[dict],
        parent_var_name: str,
    ) -> list[dict]:
        """
        Extract child variables from GDB responses.

        :param responses: List of responses from GDB.
        :param parent_var_name: Name of the parent variable.
        :return: List of child variables.
        """
        if not responses:
            return []

        for resp in responses:
            if resp.get("type") == "result" and resp.get("message") == "done":
                payload = resp.get("payload", {})
                children = payload.get("children", [])

                return self._parse_variable_children_response(children, parent_var_name)

        return []

    def _parse_variable_children_response(
        self,
        children: list[dict],
        parent_var_name: str,
    ) -> list[dict]:
        """
        Parse the children variables from the GDB response.

        :param children: List of child variable dictionaries.
        :param parent_var_name: Name of the parent variable.
        :return: List of parsed child variables.
        """
        results = []
        for child in children:
            parsed_child = self._parse_child_variable(child, parent_var_name)
            if parsed_child:
                results.append(parsed_child)
        return results

    def _is_complex_variable(self, value: str) -> bool:
        """
        Determine if a variable is complex (struct, array, std::vector).

        :param value: The value of the variable from GDB.
        :return: True if the variable is complex, False otherwise.
        """
        return "{" in value or "[" in value

    def _parse_child_variable(self, child: dict, parent_var_name: str) -> dict | None:
        """
        Parse a single child variable from the GDB response.

        :param child: Child variable dictionary.
        :param parent_var_name: Name of the parent variable.
        :return: Parsed variable dictionary or None if invalid.
        """
        name = child.get("exp", "<unknown>")  # Variable name
        value = child.get("value", "<unknown>")  # Value
        child_gdb_name = child.get("name", "")  # Internal name in GDB

        if not child_gdb_name:
            return None

        can_expand = self._can_expand_variable(child)
        child_var_ref = self._generate_new_var_dynamic_ref() if can_expand else 0

        if child_var_ref:
            self._var_map[child_var_ref] = child_gdb_name

        return {
            "name": name,  # Use the GDB name, not the full path
            "value": value,
            "variablesReference": child_var_ref,
        }

    def _can_expand_variable(self, var_info: dict) -> bool:
        """
        Determine if a variable can be expanded (e.g., struct, array, std::vector).

        :param var_info: Dictionary containing variable information.
        :return: True if the variable can be expanded, False otherwise.
        """
        return (
            int(var_info.get("numchild", "0")) > 0
            or var_info.get("has_more", "0") == "1"
            or var_info.get("displayhint", "") == "array"
        )
