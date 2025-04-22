"""Unit tests for the GDB variable handling module."""

from src.common import VAR_REF_DYNAMIC_BASE
from src.gdb.variables import VariableManager, escape_gdb_var_name


def test_is_hex_pointer_true(variable_manager: VariableManager):
    """Should return True for a valid hex pointer string."""
    assert variable_manager._is_hex_pointer("0xdeadbeef") is True  # noqa: WPS437


def test_is_hex_pointer_false(variable_manager: VariableManager):
    """Should return False for a non-pointer string."""
    assert variable_manager._is_hex_pointer("42") is False  # noqa: WPS437


def test_is_pointer_type_explicit_star(variable_manager: VariableManager):
    """Should detect a pointer type explicitly marked with an asterisk (*)."""
    assert variable_manager._is_pointer_type("int*", "0x0") is True  # noqa: WPS437


def test_is_pointer_type_hex_value(variable_manager: VariableManager):
    """Should detect a pointer based on hex value even if type has no asterisk."""
    assert variable_manager._is_pointer_type("int", "0x1000") is True  # noqa: WPS437


def test_is_pointer_type_nullptr(variable_manager: VariableManager):
    """Should detect a pointer if the value is 'nullptr'."""
    assert variable_manager._is_pointer_type("int", "nullptr") is True  # noqa: WPS437


def test_is_pointer_type_false(variable_manager: VariableManager):
    """Should return False for non-pointer types and non-pointer values."""
    assert variable_manager._is_pointer_type("int", "42") is False  # noqa: WPS437


def test_escape_gdb_var_name():
    """Should escape GDB variable names containing commas and quotes."""
    result = escape_gdb_var_name('a,"b",c')
    assert result == r'"a\,\"b\"\,c"'


def test_local_var_refs_for_complex_and_ptrs(
    variable_manager: VariableManager,
    monkeypatch,
):
    """Should create variable references for complex and pointer types."""
    monkeypatch.setattr(
        variable_manager,
        "create_gdb_variable",
        lambda name: {"variablesReference": VAR_REF_DYNAMIC_BASE},
    )

    monkeypatch.setattr(
        variable_manager,
        "get_local_variables_with_values",
        lambda: [
            {"name": "x", "value": "{a = 1}"},  # complex
            {"name": "y", "value": "0x1000"},  # pointer
            {"name": "z", "value": "42"},  # simple
        ],
    )

    result = variable_manager._get_local_vars()  # noqa: WPS437
    assert result == [
        {"name": "x", "value": "{a = 1}", "variablesReference": VAR_REF_DYNAMIC_BASE},
        {"name": "y", "value": "0x1000", "variablesReference": VAR_REF_DYNAMIC_BASE},
        {"name": "z", "value": "42", "variablesReference": 0},
    ]


def test_create_gdb_variable(variable_manager: VariableManager, backend_mock):
    """Should create a GDB variable and return its metadata."""
    backend_mock.send_command_and_get_result.return_value = [
        {
            "type": "result",
            "message": "done",
            "payload": {
                "name": "var_123",
                "value": "{a = 1}",
                "type": "MyStruct",
                "numchild": "1",
            },
        },
    ]

    result = variable_manager.create_gdb_variable("myvar")
    assert result["name"] == "myvar"
    assert result["value"] == "{a = 1}"
    assert result["type"] == "MyStruct"
    assert result["variablesReference"] == VAR_REF_DYNAMIC_BASE


def test_get_variable_children(variable_manager: VariableManager, backend_mock):
    """Should retrieve child variables for a given variable reference."""
    var_ref = VAR_REF_DYNAMIC_BASE
    variable_manager._var_map[var_ref] = "some_var"  # noqa: WPS437

    backend_mock.send_command_and_get_result.return_value = [
        {
            "type": "result",
            "message": "done",
            "payload": {
                "children": [
                    {
                        "name": "child1",
                        "exp": "child1",
                        "value": "42",
                        "type": "int",
                        "numchild": "0",
                    },
                ],
            },
        },
    ]

    children = variable_manager.get_variable_children(var_ref)
    assert children == [
        {"name": "child1", "value": "42", "variablesReference": 0},
    ]


def test_adds_deref_for_pointer_var(variable_manager: VariableManager, backend_mock):
    """Should add a dereference entry when processing a pointer variable."""
    var_ref = VAR_REF_DYNAMIC_BASE + 1
    variable_manager._var_map[var_ref] = "ptr"  # noqa: WPS437
    backend_mock.send_command_and_get_result.return_value = [
        {"type": "result", "message": "done", "payload": {"numchild": "1"}},
    ]

    entries: list = []
    child = {
        "name": "ptr",
        "exp": "ptr",
        "value": "0x1234",
        "type": "int*",
        "numchild": "0",  # as if the variable has not yet been dereferenced
    }

    variable_manager._process_pointer_variable(entries, child, "ptr")  # noqa: WPS437
    # the entries list must contain at least one element whose name contains *(
    assert any("*(" in entry["name"] for entry in entries)
