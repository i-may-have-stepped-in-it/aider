"""
Minimal main.py entrypoint - thin compatibility shim.

This is now reduced to the absolute minimum required for compatibility.
All startup policy has been moved to bootstrap helpers.
"""

import sys
import webbrowser

from aider import urls, utils
from aider.analytics import Analytics
from aider.bootstrap import launch as launch_bootstrap
from aider.bootstrap.git_handler import handle_git_root_recursion
from aider.bootstrap.gui import launch_gui
from aider.bootstrap.io_setup import (
    format_and_log_settings,
    resolve_file_arguments,
    setup_io_with_error_handling,
)
from aider.bootstrap.launch import (
    apply_env_and_deprecated_args,
    check_gitignore,
    check_and_load_imports,
    get_git_root,
    is_first_run_of_new_version,
    prepare_main_model,
    prepare_repo_and_runtime,
    sanity_check_repo,
    should_background_semantic_index,
    should_preload_imports,
)
from aider.bootstrap.runtime import (
    attach_runtime_services,
    dispatch_session_mode,
    handle_pre_run_actions,
    run_interactive_session,
)
from aider.bootstrap.session import (
    create_coder,
    create_commands,
    create_summarizer,
    finalize_streaming_settings,
)
from aider.bootstrap.update_flows import (
    handle_analytics_setup,
    handle_gui_flow,
    handle_hooks_setup,
    handle_shell_completions,
    handle_ssl_setup,
    handle_theme_setup,
    handle_timeout_setup,
    handle_update_flows,
    setup_git,
)
from aider.io import InputOutput
from aider.llm import litellm  # noqa: F401; properly init litellm on launch
from aider.report import report_uncaught_exceptions
from aider.versioncheck import check_version, install_from_main_branch, install_upgrade

from .dump import dump  # noqa: F401


# Re-export for backward compatibility
importlib_resources = launch_bootstrap.importlib_resources
load_dotenv_files = launch_bootstrap.load_dotenv_files


def main(argv=None, input=None, output=None, force_git_root=None, return_coder=False):
    """Main entrypoint - thin compatibility shim."""
    report_uncaught_exceptions()

    if argv is None:
        argv = sys.argv[1:]

    # Parse args and handle shell completions
    git_root_hint = force_git_root or get_git_root()
    parser, args, loaded_dotenvs, err = launch_bootstrap.parse_args(argv, git_root_hint)
    if err:
        return err

    if shell_completion_result := handle_shell_completions(parser, args):
        return shell_completion_result

    # Handle git setup and recursion
    git_root = handle_git_root_recursion(args, force_git_root=force_git_root)
    if isinstance(git_root, int):
        return git_root

    # Theme affects IO construction, so apply it before creating InputOutput.
    handle_theme_setup(args)

    # Setup IO with error handling
    io = setup_io_with_error_handling(args, input, output, io_cls=InputOutput)
    if isinstance(io, int):
        return io

    err = apply_env_and_deprecated_args(args, io)
    if err:
        return err

    # Handle SSL, timeout, and theme setup
    handle_ssl_setup(args)
    handle_timeout_setup(args)

    # Setup analytics and hooks
    analytics = handle_analytics_setup(args, io)

    # Handle update/install/check flows
    update_result = handle_update_flows(
        args,
        io,
        analytics,
        check_version_fn=check_version,
        install_from_main_branch_fn=install_from_main_branch,
        install_upgrade_fn=install_upgrade,
    )
    if update_result is not None:
        return update_result

    # Handle GUI flow
    gui_result = handle_gui_flow(
        args,
        io,
        analytics,
        return_coder=return_coder,
        launch_gui_fn=launch_gui,
    )
    if gui_result is not False:
        return gui_result

    hooks_manager = handle_hooks_setup(args, io)

    # Resolve file arguments
    fnames, read_only_fnames, git_dname, file_arg_error = resolve_file_arguments(
        args, io=io, git_root=git_root
    )
    if file_arg_error is not None:
        analytics.event("exit", reason="Invalid directory input")
        return file_arg_error

    # Handle git setup
    if args.git and git_root:
        git_root = setup_git(git_root, io)

    if args.verbose:
        for fname in loaded_dotenvs or []:
            io.tool_output(f"Loaded {fname}")

    format_and_log_settings(parser, args, io)

    # Handle first run and imports
    is_first_run = is_first_run_of_new_version(io, verbose=args.verbose)
    if should_preload_imports(args, return_coder=return_coder):
        check_and_load_imports(io, is_first_run, verbose=args.verbose)

    # Prepare main model
    handled, result, main_model, lint_cmds = prepare_main_model(
        args=args, argv=argv, io=io, analytics=analytics, git_root=git_root
    )
    if handled:
        return result

    # Prepare repo and runtime
    handled, result, repo, runtime = prepare_repo_and_runtime(
        args=args, io=io, analytics=analytics, hooks_manager=hooks_manager,
        main_model=main_model, fnames=fnames, git_dname=git_dname
    )
    if handled:
        return result

    commands = create_commands(args, io, parser, read_only_fnames, runtime=runtime)
    summarizer = create_summarizer(args, main_model)
    finalize_streaming_settings(args, io, main_model)

    coder = create_coder(
        args=args,
        io=io,
        analytics=analytics,
        main_model=main_model,
        repo=repo,
        fnames=fnames,
        read_only_fnames=read_only_fnames,
        lint_cmds=lint_cmds,
        commands=commands,
        summarizer=summarizer,
        runtime=runtime,
        background_semantic_index=should_background_semantic_index(
            args, return_coder=return_coder
        ),
    )
    if isinstance(coder, int):
        return coder

    if return_coder:
        analytics.event("exit", reason="Returning coder object")
        return coder

    # Attach runtime services
    attach_runtime_services(args, coder, analytics, git_root, hooks_manager)

    handled, result = handle_pre_run_actions(
        args=args, io=io, coder=coder, commands=commands, analytics=analytics,
        main_model=main_model, git_root=git_root, is_first_run=is_first_run,
        urls_module=urls, webbrowser_module=webbrowser, utils_module=utils,
        fnames=fnames
    )
    if handled:
        return result

    handled, result = dispatch_session_mode(args, io, coder, analytics)
    if handled:
        return result

    return run_interactive_session(args, io, coder, analytics, hooks_manager)


if __name__ == "__main__":
    status = main()
    sys.exit(status)
