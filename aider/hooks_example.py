"""
Example hooks file for Aider.

This file demonstrates how to create custom hooks for Aider.
To use this file:
1. Copy it to a directory (e.g., ~/.aider/hooks/)
2. Rename it to something descriptive (e.g., my_hooks.py)
3. Run aider with --hooks-dir ~/.aider/hooks/

Each hook function receives context-specific arguments and can optionally
return a dictionary to modify behavior.
"""

import datetime
import json
from pathlib import Path


def register_hooks(hooks_manager):
    """
    Register all hooks with the hooks manager.
    
    This function is called automatically when the hooks file is loaded.
    Use it to register callbacks for the hook points you want to use.
    
    Args:
        hooks_manager: The HooksManager instance to register with
    """
    
    # Register command hooks
    hooks_manager.register("pre_command", on_pre_command)
    hooks_manager.register("post_command", on_post_command)
    
    # Register message/LLM hooks
    hooks_manager.register("pre_send", on_pre_send)
    hooks_manager.register("post_send", on_post_send)
    
    # Register edit hooks
    hooks_manager.register("pre_edit", on_pre_edit)
    hooks_manager.register("post_edit", on_post_edit)
    
    # Register lifecycle hooks
    hooks_manager.register("on_init", on_init)
    hooks_manager.register("on_exit", on_exit)
    
    hooks_manager.io.tool_output("Example hooks registered successfully!")


def on_pre_command(cmd_name, args, io, **kwargs):
    """
    Called before a command is executed.
    
    Args:
        cmd_name: Name of the command being executed
        args: Arguments passed to the command
        io: InputOutput instance for user interaction
        
    Returns:
        Optional dict with 'args' key to modify command arguments
    """
    io.tool_output(f"[hook] About to execute command: {cmd_name}")
    
    # Example: Log commands to a file
    log_dir = Path.home() / ".aider" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "commands.log"
    
    with open(log_file, "a") as f:
        timestamp = datetime.datetime.now().isoformat()
        f.write(f"{timestamp} - {cmd_name}: {args}\n")
    
    # Return None or an empty dict - no modifications needed
    return None


def on_post_command(cmd_name, args, result, io, **kwargs):
    """
    Called after a command is executed.
    
    Args:
        cmd_name: Name of the command that was executed
        args: Arguments passed to the command
        result: Return value of the command
        io: InputOutput instance for user interaction
    """
    io.tool_output(f"[hook] Command {cmd_name} completed")
    
    # Example: Track command usage
    if cmd_name == "add":
        io.tool_output("[hook] Files were added to the chat")
    elif cmd_name == "commit":
        io.tool_output("[hook] Changes were committed")


def on_pre_send(message, coder, **kwargs):
    """
    Called before sending a message to the LLM.
    
    Args:
        message: The message text being sent
        coder: The Coder instance
        
    Returns:
        Optional dict with 'message' key to modify the message
    """
    # Example: Log the message length
    if coder.io:
        coder.io.tool_output(f"[hook] Sending message with {len(message)} characters")
    
    # Example: Add a signature to certain messages
    if "TODO:" in message.upper():
        message += "\n\n(Note: This message contains a TODO item)"
        return {"message": message}
    
    return None


def on_post_send(message, response, coder, **kwargs):
    """
    Called after receiving a response from the LLM.
    
    Args:
        message: The original message sent
        response: The response received from the LLM
        coder: The Coder instance
    """
    if coder.io and response:
        coder.io.tool_output(f"[hook] Received response with {len(response)} characters")
    
    # Example: Log interactions for analysis
    log_dir = Path.home() / ".aider" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "interactions.jsonl"
    
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "message_length": len(message),
        "response_length": len(response) if response else 0,
    }
    
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def on_pre_edit(edits, coder, **kwargs):
    """
    Called before applying edits to files.
    
    Args:
        edits: List of edit tuples (path, original, updated)
        coder: The Coder instance
        
    Returns:
        Optional dict with 'edits' key to modify the edits list
    """
    if coder.io:
        coder.io.tool_output(f"[hook] Preparing to apply {len(edits)} edits")
    
    # Example: Create backups before editing
    for edit in edits:
        path = edit[0]
        if path:
            backup_path = str(path) + ".backup"
            try:
                with open(path, "r") as f:
                    content = f.read()
                with open(backup_path, "w") as f:
                    f.write(content)
            except Exception:
                pass  # Ignore backup errors
    
    return None


def on_post_edit(edited_files, coder, **kwargs):
    """
    Called after applying edits to files.
    
    Args:
        edited_files: Set of file paths that were edited
        coder: The Coder instance
    """
    if coder.io and edited_files:
        coder.io.tool_output(f"[hook] Edited {len(edited_files)} files: {', '.join(edited_files)}")
    
    # Example: Trigger custom linting or validation
    # You could run custom tests, formatters, etc. here


def on_init(args, io, **kwargs):
    """
    Called when Aider initializes.
    
    Args:
        args: Parsed command line arguments
        io: InputOutput instance
    """
    io.tool_output("[hook] Aider is initializing...")
    
    # Example: Check for custom configuration
    custom_config = Path.home() / ".aider" / "custom_config.json"
    if custom_config.exists():
        io.tool_output(f"[hook] Found custom config: {custom_config}")


def on_exit(coder, **kwargs):
    """
    Called when Aider is about to exit.
    
    Args:
        coder: The Coder instance
    """
    if coder.io:
        coder.io.tool_output("[hook] Aider is exiting...")
    
    # Example: Clean up temporary files, save session state, etc.


# Advanced example: Custom skill
def register_custom_skill(hooks_manager):
    """
    Example of registering a custom skill that provides reusable functionality.
    
    Skills are specialized hooks that can be enabled/disabled via --enable-skills.
    """
    
    def auto_formatter(edits, coder, **kwargs):
        """
        Automatically format code before applying edits.
        This is a simplified example - real implementation would use actual formatters.
        """
        formatted_edits = []
        for edit in edits:
            path, original, updated = edit
            if path and path.endswith(".py"):
                # Example: Strip trailing whitespace
                updated = "\n".join(line.rstrip() for line in updated.split("\n"))
            formatted_edits.append((path, original, updated))
        
        return {"edits": formatted_edits}
    
    hooks_manager.register("pre_edit", auto_formatter)


# Note: To use the custom skill, you would:
# 1. Save this file to your skills directory
# 2. Run aider with --enable-skills --skill-path /path/to/skills/
