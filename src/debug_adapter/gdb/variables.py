"""
Module for managing variables in GDB.

This module provides functionality for fetching local variables, registers,
and variable children, as well as handling GDB's variable objects.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from debug_adapter.gdb.backend import GDBBackend

from debug_adapter.common import VAR_REF_DYNAMIC_BASE, VAR_REF_LOCAL_BASE, VAR_REF_REGISTERS_BASE
from debug_adapter.gdb.gdb_utils import is_success_response

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
            if self._is_complex_variable(value) or self._is_pointer_value(value):
                var_ref = self.create_gdb_variable(var_name)["variablesReference"]
            else:
                var_ref = VAR_REF_NO_NESTING
            parsed_vars.append(
                {
                    "name": var_name,
                    "value": value,
                    "variablesReference": var_ref,
                },
            )
        return parsed_vars

    def check_for_local_variables(self) -> bool:
        """Check if there are any local variables in the current frame."""
        responses = self.backend.send_command_and_get_result("-stack-list-variables --all-values")
        vars_list = self._extract_payload_field(responses, "variables")
        return bool(vars_list)

    def check_for_registers(self) -> bool:
        """
        Fetch only the names of registers for the current frame from GDB.

        :return: List of variable names.
        """
        responses = self.backend.send_command_and_get_result("-data-list-register-names")
        register_list = self._extract_payload_field(responses, "register-names")
        return bool(register_list)

    def get_local_variables_with_values(self) -> list[dict]:
        """
        Fetch local variables with their values for the current frame from GDB.

        :return: List of dictionaries containing variable names and values.
        """
        responses = self.backend.send_command_and_get_result("-stack-list-variables --all-values")
        vars_list = self._extract_payload_field(responses, "variables")
        return vars_list if vars_list else []

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
        payload = self._parse_gdb_response(responses)
        return self._extract_variable_from_payload(payload, var_name) if payload else {}

    def _parse_gdb_response(self, responses: list[dict]) -> dict | None:
        for resp in responses:
            if is_success_response(resp):
                return resp.get("payload", {})
        return None

    def _extract_variable_from_payload(self, payload: dict, var_name: str) -> dict:
        numchild = int(payload.get("numchild", "0"))
        has_more = payload.get("has_more", "0")
        displayhint = payload.get("displayhint", "")

        can_expand = numchild > 0 or has_more == "1" or displayhint == "array"
        gdb_var_name = payload.get("name", "")

        var_ref = VAR_REF_NO_NESTING
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
        escaped_name = escape_gdb_var_name(gdb_var_name)
        cmd = f"-var-list-children --all-values {escaped_name}"
        responses = self.backend.send_command_and_get_result(cmd)
        return self._extract_variable_children_from_response(responses)

    def _extract_variable_children_from_response(
        self,
        responses: list[dict],
    ) -> list[dict]:
        if not responses:
            return []
        for resp in responses:
            if is_success_response(resp):
                children = resp.get("payload", {}).get("children", [])
                return self._parse_variable_children_response(children)
        return []

    def _parse_variable_children_response(
        self,
        children: list[dict],
    ) -> list[dict]:
        results = []
        for child in children:
            parsed = self._parse_child_variable(child)
            if parsed:
                results.extend(parsed)
        return results

    def _parse_child_variable(self, child: dict) -> list[dict] | None:
        child_gdb_name = child.get("name", "")
        if not child_gdb_name:
            return None

        entries = []
        child_var_ref = (
            self._generate_new_var_dynamic_ref() if self._can_expand_variable(child) else 0
        )
        if child_var_ref:
            self._var_map[child_var_ref] = child_gdb_name

        entries.append(
            {
                "name": child.get("exp", "<unknown>"),
                "value": child.get("value", "<unknown>"),
                "variablesReference": child_var_ref,
            },
        )

        if self._is_pointer_type(child.get("type", ""), child.get("value", "<unknown>")):
            self._process_pointer_variable(entries, child, child_gdb_name)

        return entries

    def _process_pointer_variable(self, entries: list[dict], child: dict, child_gdb_name: str):
        deref_var_name = f"*({child_gdb_name})"
        deref_var_ref = self._generate_new_var_dynamic_ref()
        self._var_map[deref_var_ref] = deref_var_name

        escaped_deref_name = escape_gdb_var_name(deref_var_name)
        command = f"-var-list-children --all-values {escaped_deref_name}"
        responses = self.backend.send_command_and_get_result(command)
        deref_display_name = child.get("exp", "<unknown>")

        if self._has_children(responses):
            entries.append(
                {
                    "name": f"*({deref_display_name})",
                    "value": "",
                    "variablesReference": deref_var_ref,
                },
            )

    def _has_children(self, responses: list[dict]) -> bool:
        for resp in responses:
            if not is_success_response(resp):
                continue

            payload = resp.get("payload", {})
            numchild = int(payload.get("numchild", "0"))
            if numchild > 0:
                return True
        return False

    def _can_expand_variable(self, var_info: dict) -> bool:
        return (
            int(var_info.get("numchild", "0")) > 0
            or var_info.get("has_more", "0") == "1"
            or var_info.get("displayhint", "") == "array"
        )

    def _is_complex_variable(self, value: str) -> bool:
        return "{" in value or "[" in value

    def _is_pointer_type(self, var_type: str, value: str) -> bool:
        if "*" in var_type.replace(" ", ""):
            return True
        if self._is_hex_pointer(value):
            return True
        return value.strip() in {"0x0", "NULL", "nullptr"}

    def _is_pointer_value(self, value: str) -> bool:
        return self._is_hex_pointer(value) and value.strip() != "0x0"

    def _is_hex_pointer(self, value: str) -> bool:
        return bool(re.fullmatch("0x[0-9a-fA-F]+", value.strip()))

    def _extract_payload_field(self, responses: list[dict], field: str) -> list | None:
        for resp in responses:
            if is_success_response(resp):
                return resp.get("payload", {}).get(field)
        return None


def escape_gdb_var_name(name: str) -> str:
    """Escape special characters in a GDB variable name."""
    escaped = name.replace(",", r"\,").replace('"', r"\"")
    return f'"{escaped}"'
