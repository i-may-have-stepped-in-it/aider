"""
Legacy compatibility wrappers over the canonical startup modules.

The active startup path should go directly through:
- `aider.bootstrap.launch`
- `aider.bootstrap.session`
- `aider.bootstrap.runtime`
"""

from aider.bootstrap.launch import should_background_semantic_index
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
from aider.bootstrap.update_flows import handle_update_flows


def handle_pre_run_actions_orchestration(
    args,
    io,
    coder,
    commands,
    analytics,
    main_model,
    git_root,
    is_first_run,
    urls_module,
    webbrowser_module,
    utils_module,
    fnames,
):
    """Compatibility wrapper around `bootstrap.runtime.handle_pre_run_actions`."""
    handled, result = handle_pre_run_actions(
        args=args,
        io=io,
        coder=coder,
        commands=commands,
        analytics=analytics,
        main_model=main_model,
        git_root=git_root,
        is_first_run=is_first_run,
        urls_module=urls_module,
        webbrowser_module=webbrowser_module,
        utils_module=utils_module,
        fnames=fnames,
    )
    if handled:
        return result
    return None


def handle_pre_run_update_check(args, io, analytics):
    """Compatibility wrapper around the active update-flow handler."""
    return handle_update_flows(args, io, analytics)


def handle_interactive_session_launch(args, io, coder, analytics, hooks_manager):
    """Compatibility wrapper around runtime dispatch helpers."""
    handled, result = dispatch_session_mode(args, io, coder, analytics)
    if handled:
        return result

    return run_interactive_session(args, io, coder, analytics, hooks_manager)


def attach_runtime_services_comprehensive(args, coder, analytics, git_root, hooks_manager):
    """Compatibility wrapper around `bootstrap.runtime.attach_runtime_services`."""
    return attach_runtime_services(args, coder, analytics, git_root, hooks_manager)


def create_session_components(
    args,
    io,
    parser,
    analytics,
    main_model,
    repo,
    fnames,
    read_only_fnames,
    lint_cmds,
    runtime,
    background_semantic_index=True,
):
    """Compatibility wrapper around the canonical session helpers."""
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
        background_semantic_index=background_semantic_index,
    )

    if isinstance(coder, int):
        return coder, None, None

    return coder, commands, summarizer


__all__ = [
    "attach_runtime_services_comprehensive",
    "create_coder",
    "create_commands",
    "create_session_components",
    "create_summarizer",
    "dispatch_session_mode",
    "finalize_streaming_settings",
    "handle_interactive_session_launch",
    "handle_pre_run_actions",
    "handle_pre_run_actions_orchestration",
    "handle_pre_run_update_check",
    "run_interactive_session",
    "should_background_semantic_index",
]
