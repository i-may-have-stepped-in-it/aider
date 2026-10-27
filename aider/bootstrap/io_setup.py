"""
Enterprise bootstrap helpers for aider startup.

This module contains high-level orchestration functions that were
previously embedded directly in main.py. Moving them here allows
main.py to remain a thin compatibility shim.
"""

import sys
from pathlib import Path
from typing import Optional

from aider.bootstrap.launch import (
    should_background_semantic_index as launch_should_background_semantic_index,
    should_preload_imports as launch_should_preload_imports,
)


def setup_io_with_error_handling(args, input=None, output=None, io_cls=None):
    """
    Setup InputOutput with proper error handling.
    
    This function handles Unicode encoding errors gracefully by
    falling back to non-pretty mode if the terminal doesn't support
    the full Unicode output.
    
    Args:
        args: Parsed command line arguments
        input: Optional input stream override
        output: Optional output stream override
        
    Returns:
        InputOutput instance, or int error code on failure
    """
    from prompt_toolkit.enums import EditingMode

    if io_cls is None:
        from aider.io import InputOutput

        io_cls = InputOutput

    try:
        editing_mode = EditingMode.VI if args.vim else EditingMode.EMACS
        
        io = io_cls(
            args.pretty,
            args.yes_always,
            args.input_history_file,
            args.chat_history_file,
            input=input,
            output=output,
            user_input_color=args.user_input_color,
            tool_output_color=args.tool_output_color,
            tool_warning_color=args.tool_warning_color,
            tool_error_color=args.tool_error_color,
            completion_menu_color=args.completion_menu_color,
            completion_menu_bg_color=args.completion_menu_bg_color,
            completion_menu_current_color=args.completion_menu_current_color,
            completion_menu_current_bg_color=args.completion_menu_current_bg_color,
            assistant_output_color=args.assistant_output_color,
            code_theme=args.code_theme,
            dry_run=args.dry_run,
            encoding=args.encoding,
            line_endings=args.line_endings,
            llm_history_file=args.llm_history_file,
            editingmode=editing_mode,
            fancy_input=args.fancy_input,
            multiline_mode=args.multiline,
            notifications=args.notifications,
            notifications_command=args.notifications_command,
            enable_dashboard=args.dashboard,
            theme=getattr(args, "theme", None),
        )
        
        io.rule()
        return io
        
    except UnicodeEncodeError as err:
        if not args.pretty:
            raise err
        io = io_cls(
            False,  # Force non-pretty
            args.yes_always,
            args.input_history_file,
            args.chat_history_file,
            input=input,
            output=output,
        )
        io.tool_warning("Terminal does not support pretty output (UnicodeDecodeError)")
        return io


def resolve_file_arguments(args, io=None, git_root=None):
    """
    Resolve file arguments from command line and args.
    
    Returns:
        tuple: (fnames, read_only_fnames, git_dname, error_code) resolved file paths
    """
    all_files = list(getattr(args, "files", []) or []) + list(getattr(args, "file", []) or [])
    fnames = [str(Path(fn).resolve()) for fn in all_files]
    read_only_fnames = []
    git_dname = None

    for fname in getattr(args, "read", []) or []:
        path = Path(fname).expanduser().resolve()
        if path.is_dir():
            read_only_fnames.extend(str(f) for f in path.rglob("*") if f.is_file())
        else:
            read_only_fnames.append(str(path))

    if len(all_files) > 1:
        good = True
        for fname in all_files:
            if Path(fname).is_dir():
                if io:
                    io.tool_error(f"{fname} is a directory, not provided alone.")
                good = False
        if not good:
            if io:
                io.tool_output(
                    "Provide either a single directory of a git repo, or a list of one or more files."
                )
            return None, None, None, 1

    if len(all_files) == 1:
        only_path = Path(all_files[0])
        if only_path.is_dir():
            if getattr(args, "git", True):
                git_dname = str(only_path.resolve())
                fnames = []
            else:
                if io:
                    io.tool_error(f"{all_files[0]} is a directory, but --no-git selected.")
                return None, None, None, 1

    return fnames, read_only_fnames, git_dname, None


def format_and_log_settings(parser, args, io):
    """
    Format and display settings if verbose mode is enabled.
    Also logs the command line (scrubbed of sensitive info).
    
    Args:
        parser: The argument parser
        args: Parsed arguments
        io: InputOutput instance
    """
    from aider.format_settings import format_settings, scrub_sensitive_info

    # Format and display settings if verbose
    if args.verbose:
        show = format_settings(parser, args)
        io.tool_output(show)
    
    # Log command line (scrubbed)
    cmd_line = " ".join(sys.argv)
    cmd_line = scrub_sensitive_info(args, cmd_line)
    io.tool_output(cmd_line, log_only=True)


def should_skip_import_preload(args, return_coder=False):
    """Legacy wrapper around the canonical preload policy."""
    return not launch_should_preload_imports(args, return_coder=return_coder)


def should_background_semantic_index(args, return_coder=False):
    """Legacy wrapper around the canonical semantic-index policy."""
    return launch_should_background_semantic_index(args, return_coder=return_coder)
