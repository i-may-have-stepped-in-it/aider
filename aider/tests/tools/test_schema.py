"""Tests for ToolSchemaGenerator.

This module tests the ToolSchemaGenerator class which generates OpenAI-compatible
tool schemas from aider's Commands class.
"""

import pytest
from aider.tools.schema import ToolSchemaGenerator, get_tool_schemas, get_tool_schema, get_tool_descriptions


class TestToolSchemaGenerator:
    """Test suite for ToolSchemaGenerator class."""

    def test_generate_all_returns_list(self):
        """Verify generate_all() returns a list of tool schemas.
        
        This test ensures that generate_all() returns a valid list structure
        that can be used with litellm or OpenAI-compatible APIs.
        """
        schemas = ToolSchemaGenerator.generate_all()
        
        assert isinstance(schemas, list)
        assert len(schemas) > 0

    def test_generate_all_contains_expected_tools(self):
        """Verify generate_all() includes all expected tools.
        
        Ensures that core tools like run, add, read_file, etc. are present
        in the generated schemas.
        """
        schemas = ToolSchemaGenerator.generate_all()
        tool_names = {schema["function"]["name"] for schema in schemas}
        
        expected_tools = {"run", "add", "read_file", "search", "git", "ls", "drop", "commit"}
        assert expected_tools.issubset(tool_names)

    def test_each_tool_has_required_fields(self):
        """Verify each tool schema has required OpenAI-compatible fields.
        
        Each tool schema must have:
        - type: should be "function"
        - function: containing name, description, and parameters
        """
        schemas = ToolSchemaGenerator.generate_all()
        
        for schema in schemas:
            assert "type" in schema
            assert schema["type"] == "function"
            assert "function" in schema
            
            func = schema["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func
            
            # Name should be non-empty string
            assert isinstance(func["name"], str)
            assert len(func["name"]) > 0
            
            # Description should be non-empty string
            assert isinstance(func["description"], str)
            assert len(func["description"]) > 0

    def test_parameters_have_required_structure(self):
        """Verify parameter definitions have correct structure.
        
        Parameters must have:
        - type: should be "object"
        - properties: dict of parameter definitions
        - additionalProperties: boolean flag
        """
        schemas = ToolSchemaGenerator.generate_all()
        
        for schema in schemas:
            params = schema["function"]["parameters"]
            
            assert "type" in params
            assert params["type"] == "object"
            assert "properties" in params
            assert isinstance(params["properties"], dict)
            assert "additionalProperties" in params
            assert isinstance(params["additionalProperties"], bool)

    def test_parameter_properties_have_descriptions(self):
        """Verify each parameter has a description.
        
        All parameters should have descriptions to help the LLM understand
        how to use them correctly.
        """
        schemas = ToolSchemaGenerator.generate_all()
        
        for schema in schemas:
            params = schema["function"]["parameters"]
            properties = params.get("properties", {})
            
            for param_name, param_def in properties.items():
                assert "description" in param_def, f"Parameter {param_name} missing description"
                assert isinstance(param_def["description"], str)
                assert len(param_def["description"]) > 0

    def test_get_tool_schema_for_specific_tools(self):
        """Verify get_tool_schema() returns correct schema for specific tools.
        
        Tests that we can retrieve individual tool schemas by name.
        """
        # Test for 'run' tool
        run_schema = ToolSchemaGenerator.get_tool_schema("run")
        assert run_schema is not None
        assert run_schema["function"]["name"] == "run"
        assert "command" in run_schema["function"]["parameters"]["properties"]
        
        # Test for 'add' tool
        add_schema = ToolSchemaGenerator.get_tool_schema("add")
        assert add_schema is not None
        assert add_schema["function"]["name"] == "add"
        assert "files" in add_schema["function"]["parameters"]["properties"]
        
        # Test for 'read_file' tool
        read_schema = ToolSchemaGenerator.get_tool_schema("read_file")
        assert read_schema is not None
        assert read_schema["function"]["name"] == "read_file"
        assert "path" in read_schema["function"]["parameters"]["properties"]

    def test_get_tool_schema_returns_none_for_unknown(self):
        """Verify get_tool_schema() returns None for unknown tools."""
        result = ToolSchemaGenerator.get_tool_schema("nonexistent_tool")
        assert result is None

    def test_get_required_params_with_required_params(self):
        """Verify get_required_params() for tools with required params.
        
        Tools like 'run' and 'add' have required parameters.
        """
        # 'run' tool requires 'command' parameter
        required = ToolSchemaGenerator.get_required_params("run")
        assert "command" in required
        
        # 'add' tool requires 'files' parameter
        required = ToolSchemaGenerator.get_required_params("add")
        assert "files" in required
        
        # 'read_file' tool requires 'path' parameter
        required = ToolSchemaGenerator.get_required_params("read_file")
        assert "path" in required

    def test_get_required_params_without_required_params(self):
        """Verify get_required_params() for tools without required params.
        
        Tools like 'ls' have no required parameters.
        """
        # 'ls' tool has no required parameters
        required = ToolSchemaGenerator.get_required_params("ls")
        assert required == []
        
        # 'drop' tool has empty required list
        required = ToolSchemaGenerator.get_required_params("drop")
        assert isinstance(required, list)

    def test_get_required_params_for_unknown_tool(self):
        """Verify get_required_params() returns empty list for unknown tools."""
        required = ToolSchemaGenerator.get_required_params("unknown_tool")
        assert required == []

    def test_validate_tool_call_with_valid_params(self):
        """Verify validate_tool_call() accepts valid parameter sets.
        
        Tests that validation passes when all required parameters are present.
        """
        # Valid 'run' call with required parameter
        valid, error = ToolSchemaGenerator.validate_tool_call("run", {"command": "ls -la"})
        assert valid is True
        assert error is None
        
        # Valid 'add' call with required parameter
        valid, error = ToolSchemaGenerator.validate_tool_call("add", {"files": ["test.py"]})
        assert valid is True
        assert error is None
        
        # Valid 'ls' call with no parameters
        valid, error = ToolSchemaGenerator.validate_tool_call("ls", {})
        assert valid is True
        assert error is None

    def test_validate_tool_call_with_missing_required_params(self):
        """Verify validate_tool_call() rejects missing required parameters.
        
        Tests that validation fails when required parameters are missing.
        """
        # Invalid 'run' call missing required 'command' parameter
        valid, error = ToolSchemaGenerator.validate_tool_call("run", {})
        assert valid is False
        assert error is not None
        assert "required" in error.lower() or "missing" in error.lower()
        
        # Invalid 'add' call missing required 'files' parameter
        valid, error = ToolSchemaGenerator.validate_tool_call("add", {})
        assert valid is False
        assert error is not None

    def test_validate_tool_call_with_unknown_params(self):
        """Verify validate_tool_call() rejects unknown parameters.
        
        When additionalProperties is False, unknown parameters should be rejected.
        """
        # 'run' tool doesn't allow additional properties
        valid, error = ToolSchemaGenerator.validate_tool_call(
            "run", {"command": "ls", "unknown_param": "value"}
        )
        assert valid is False
        assert error is not None
        assert "unknown" in error.lower()

    def test_validate_tool_call_for_unknown_tool(self):
        """Verify validate_tool_call() returns error for unknown tools."""
        valid, error = ToolSchemaGenerator.validate_tool_call("unknown_tool", {})
        assert valid is False
        assert error is not None
        assert "unknown" in error.lower()

    def test_get_command_schemas_returns_dict(self):
        """Verify get_command_schemas() returns dictionary mapping.
        
        The returned dict should map command names to their schemas.
        """
        schemas = ToolSchemaGenerator.get_command_schemas()
        
        assert isinstance(schemas, dict)
        assert "run" in schemas
        assert "add" in schemas
        assert "read_file" in schemas
        
        # Each value should be a valid schema
        for name, schema in schemas.items():
            assert schema["function"]["name"] == name

    def test_get_command_schemas_returns_copy(self):
        """Verify get_command_schemas() returns a copy, not the original.
        
        Modifications to the returned dict should not affect the original.
        """
        schemas = ToolSchemaGenerator.get_command_schemas()
        original_count = len(schemas)
        
        # Modify the returned dict
        schemas["new_tool"] = {"test": "data"}
        
        # Get schemas again - should not have the new tool
        schemas2 = ToolSchemaGenerator.get_command_schemas()
        assert len(schemas2) == original_count
        assert "new_tool" not in schemas2

    def test_get_tool_description(self):
        """Verify get_tool_description() returns correct descriptions."""
        # Known tool
        desc = ToolSchemaGenerator.get_tool_description("run")
        assert desc is not None
        assert "shell" in desc.lower() or "command" in desc.lower()
        
        # Unknown tool
        desc = ToolSchemaGenerator.get_tool_description("unknown")
        assert desc is None

    def test_get_tool_names(self):
        """Verify get_tool_names() returns sorted list of all tools."""
        names = ToolSchemaGenerator.get_tool_names()
        
        assert isinstance(names, list)
        assert len(names) > 0
        
        # Should be sorted
        assert names == sorted(names)
        
        # Should contain expected tools
        assert "run" in names
        assert "add" in names
        assert "ls" in names


class TestConvenienceFunctions:
    """Test suite for convenience functions."""

    def test_get_tool_schemas(self):
        """Verify get_tool_schemas() convenience function works."""
        schemas = get_tool_schemas()
        
        assert isinstance(schemas, list)
        assert len(schemas) > 0
        
        # Should match generate_all()
        assert schemas == ToolSchemaGenerator.generate_all()

    def test_get_tool_schema_convenience(self):
        """Verify get_tool_schema() convenience function works."""
        schema = get_tool_schema("run")
        
        assert schema is not None
        assert schema["function"]["name"] == "run"
        
        # Should match class method
        assert schema == ToolSchemaGenerator.get_tool_schema("run")

    def test_get_tool_descriptions(self):
        """Verify get_tool_descriptions() returns all tool descriptions."""
        descriptions = get_tool_descriptions()
        
        assert isinstance(descriptions, dict)
        assert "run" in descriptions
        assert "add" in descriptions
        
        # Each description should be a string
        for name, desc in descriptions.items():
            assert isinstance(desc, str)
            assert len(desc) > 0


class TestSchemaContent:
    """Test suite for verifying schema content accuracy."""

    def test_run_tool_description(self):
        """Verify 'run' tool has accurate description."""
        schema = ToolSchemaGenerator.get_tool_schema("run")
        desc = schema["function"]["description"]
        
        assert "shell" in desc.lower()
        assert "command" in desc.lower()

    def test_add_tool_files_parameter(self):
        """Verify 'add' tool files parameter is array type."""
        schema = ToolSchemaGenerator.get_tool_schema("add")
        files_param = schema["function"]["parameters"]["properties"]["files"]
        
        assert files_param["type"] == "array"
        assert "items" in files_param
        assert files_param["items"]["type"] == "string"

    def test_search_tool_optional_path(self):
        """Verify 'search' tool has optional path parameter."""
        schema = ToolSchemaGenerator.get_tool_schema("search")
        params = schema["function"]["parameters"]
        
        # pattern is required
        assert "pattern" in params["required"]
        
        # path is optional (not in required)
        assert "path" not in params["required"]

    def test_git_tool_parameter_description(self):
        """Verify 'git' tool has clear parameter description."""
        schema = ToolSchemaGenerator.get_tool_schema("git")
        command_param = schema["function"]["parameters"]["properties"]["command"]
        
        assert "git" in command_param["description"].lower()
        assert "subcommand" in command_param["description"].lower() or "command" in command_param["description"].lower()

    def test_ls_tool_has_no_properties(self):
        """Verify 'ls' tool has empty properties."""
        schema = ToolSchemaGenerator.get_tool_schema("ls")
        properties = schema["function"]["parameters"]["properties"]
        
        assert properties == {}

    def test_commit_message_optional(self):
        """Verify 'commit' tool has optional message parameter."""
        schema = ToolSchemaGenerator.get_tool_schema("commit")
        params = schema["function"]["parameters"]
        
        # message is optional
        assert "message" not in params["required"]
        assert "message" in params["properties"]
