"""
Main entry point for Aider (async by default).

This module provides the primary entry point for Aider,
using async/await for non-blocking prompt input during generation.
"""

import asyncio
import shutil
import sys


def run_async_main(argv=None, input=None, output=None, force_git_root=None, return_coder=False):
    """Run the async version of main."""
    return asyncio.run(async_main(argv, input, output, force_git_root, return_coder))


async def async_main(
    argv=None,
    input=None,
    output=None,
    force_git_root=None,
    return_coder=False,
):
    """
    Async main entry point for Aider.
    
    This is the async version that enables true background generation
    with persistent prompt (Option B).
    """
    from aider import urls, utils
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
        check_and_load_imports,
        check_gitignore,
        get_git_root,
        guessed_wrong_repo,
        is_first_run_of_new_version,
        make_new_repo,
        prepare_main_model,
        prepare_repo_and_runtime,
        should_background_semantic_index,
        should_preload_imports,
        parse_args,
    )
    import git
    from pathlib import Path
    from aider.bootstrap.runtime import (
        attach_runtime_services,
        dispatch_session_mode,
        handle_pre_run_actions,
        run_interactive_session_async,
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
    from aider.llm import litellm  # noqa: F401; properly init litellm on launch
    from aider.report import report_uncaught_exceptions
    from aider.versioncheck import check_version, install_from_main_branch, install_upgrade
    from aider.io import InputOutput
    import webbrowser
    
    report_uncaught_exceptions()

    if argv is None:
        argv = sys.argv[1:]

    # Parse args and handle shell completions
    git_root_hint = force_git_root or get_git_root()
    parser, args, loaded_dotenvs, err = parse_args(argv, git_root_hint)
    if err:
        return err

    if shell_completion_result := handle_shell_completions(parser, args):
        return shell_completion_result

    # Handle git setup and recursion
    git_root = handle_git_root_recursion(args, force_git_root=force_git_root)
    if isinstance(git_root, int):
        return git_root

    # Theme affects IO construction
    handle_theme_setup(args)

    # Setup IO
    io = setup_io_with_error_handling(args, input, output, io_cls=InputOutput)
    if isinstance(io, int):
        return io

    err = apply_env_and_deprecated_args(args, io)
    if err:
        return err

    handle_ssl_setup(args)
    handle_timeout_setup(args)

    analytics = handle_analytics_setup(args, io)

    # Handle update flows
    update_result = handle_update_flows(
        args, io, analytics,
        check_version_fn=check_version,
        install_from_main_branch_fn=install_from_main_branch,
        install_upgrade_fn=install_upgrade,
    )
    if update_result is not None:
        return update_result

    # Handle GUI flow
    gui_result = handle_gui_flow(args, io, analytics, return_coder=return_coder, launch_gui_fn=launch_gui)
    if gui_result is not False:
        return gui_result

    hooks_manager = handle_hooks_setup(args, io)

    # Resolve file arguments
    fnames, read_only_fnames, git_dname, file_arg_error = resolve_file_arguments(args, io=io, git_root=git_root)
    if file_arg_error is not None:
        analytics.event("exit", reason="Invalid directory input")
        return file_arg_error

    # Recalibrate repo if we guessed wrong initially
    new_git_root = guessed_wrong_repo(io, git_root, fnames, git_dname)
    if new_git_root:
        git_root = new_git_root

    # Handle git setup
    if args.git:
        # If no repo found but we have files, try to make one if allowed
        if not git_root and fnames and args.yes_always:
            git_root = str(Path(fnames[0]).parent)
            make_new_repo(git_root, io)
        
        if git_root:
            git_root = setup_git(git_root, io)

    # Final check for gitignore and aiderignore
    check_gitignore(git_root, io)

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

    # Update IO with model and branch info early
    if git_root:
        try:
            repo_obj = git.Repo(git_root)
            io.set_git_branch(repo_obj.active_branch.name)
        except Exception:
            pass
    io.set_model(main_model.name)

    # Prepare repo and runtime
    handled, result, repo, runtime = prepare_repo_and_runtime(
        args=args, io=io, analytics=analytics, hooks_manager=hooks_manager,
        main_model=main_model, fnames=fnames, git_dname=git_dname or git_root
    )
    if handled:
        return result

    commands = create_commands(args, io, parser, read_only_fnames, runtime=runtime)
    summarizer = create_summarizer(args, main_model)
    finalize_streaming_settings(args, io, main_model)

    # Create coder - this now uses async internally
    coder = create_coder(
        args=args, io=io, analytics=analytics, main_model=main_model,
        repo=repo, fnames=fnames, read_only_fnames=read_only_fnames,
        lint_cmds=lint_cmds, commands=commands, summarizer=summarizer,
        runtime=runtime, background_semantic_index=False,  # Disabled for async
    )
    if isinstance(coder, int):
        return coder

    # Update status bar with model and git info
    if main_model:
        io.set_model(main_model.name)
    if repo:
        io.set_git_branch(repo.get_branch_name())

    # Clear screen on startup for modernized TUI
    if args.pretty and io.fancy_input:
        io.clear()
        # Push prompt to bottom by printing newlines
        try:
            lines = shutil.get_terminal_size().lines
            print("\n" * (lines - 5))
        except Exception:
            pass

    if return_coder:
        analytics.event("exit", reason="Returning coder object")
        return coder

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

    # Run async interactive session
    return await run_interactive_session_async(args, io, coder, analytics, hooks_manager)
