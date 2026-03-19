"""
Legacy startup-policy compatibility shims.

This module is not part of the active startup path. The canonical flow lives in:
- `aider.bootstrap.launch`
- `aider.bootstrap.session`
- `aider.bootstrap.runtime`
- `aider.bootstrap.gui`
"""

from aider.bootstrap.io_setup import setup_io_with_error_handling as setup_io_comprehensive
from aider.bootstrap.launch import (
    check_and_load_imports,
    is_first_run_of_new_version,
    prepare_main_model as prepare_main_model_logic,
    prepare_repo_and_runtime as prepare_repo_and_runtime_logic,
    should_preload_imports,
)
from aider.bootstrap.pre_run_actions import (
    attach_runtime_services_comprehensive,
    create_session_components,
    handle_interactive_session_launch,
    handle_pre_run_actions_orchestration,
)


def setup_model_and_repo(args, argv, io, analytics=None, git_root=None):
    """Compatibility wrapper around canonical model/repo preparation helpers."""
    handled, result, main_model, _lint_cmds = prepare_main_model_logic(
        args=args,
        argv=argv,
        io=io,
        analytics=analytics,
        git_root=git_root,
    )
    if handled:
        return None, None, result

    handled, result, repo, _runtime = prepare_repo_and_runtime_logic(
        args=args,
        io=io,
        analytics=analytics,
        hooks_manager=None,
        main_model=main_model,
        fnames=[],
        git_dname=None,
    )
    if handled:
        return None, None, result

    return main_model, repo, analytics


def setup_environment_configuration(args, io):
    """Legacy no-op configuration shim retained for compatibility."""
    return {}


def handle_setup_completion(args, io, analytics, git_root):
    """Compatibility wrapper for old startup completion logic."""
    if should_preload_imports(args):
        is_first_run = is_first_run_of_new_version(io, verbose=args.verbose)
        check_and_load_imports(io, is_first_run, verbose=args.verbose)
    return None


create_session_components_comprehensive = create_session_components
complete_session_setup = handle_interactive_session_launch


__all__ = [
    "attach_runtime_services_comprehensive",
    "complete_session_setup",
    "create_session_components",
    "create_session_components_comprehensive",
    "handle_interactive_session_launch",
    "handle_pre_run_actions_orchestration",
    "handle_setup_completion",
    "is_first_run_of_new_version",
    "prepare_main_model_logic",
    "prepare_repo_and_runtime_logic",
    "setup_environment_configuration",
    "setup_io_comprehensive",
    "setup_model_and_repo",
    "should_preload_imports",
]
