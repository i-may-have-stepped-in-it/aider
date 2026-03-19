"""
Update/install/check helpers for the active startup path.

This module is part of the current canonical startup flow used by
`aider.main`, but it should stay narrowly focused on update/gui/shell/theme
and analytics concerns. Broader startup orchestration belongs in
`bootstrap.launch`, `bootstrap.session`, and `bootstrap.runtime`.
"""

import os
import sys

from aider.bootstrap.launch import (
    check_gitignore,
    check_streamlit_install,
    setup_git,
)


def handle_update_flows(
    args,
    io,
    analytics,
    check_version_fn=None,
    install_from_main_branch_fn=None,
    install_upgrade_fn=None,
):
    """Handle update/install/check flows."""
    if (
        check_version_fn is None
        or install_from_main_branch_fn is None
        or install_upgrade_fn is None
    ):
        from aider.versioncheck import check_version, install_from_main_branch, install_upgrade

        check_version_fn = check_version_fn or check_version
        install_from_main_branch_fn = install_from_main_branch_fn or install_from_main_branch
        install_upgrade_fn = install_upgrade_fn or install_upgrade

    # Check for update requests
    if args.just_check_update:
        update_available = check_version_fn(io, just_check=True, verbose=args.verbose)
        analytics.event("exit", reason="Just checking update")
        return 0 if not update_available else 1

    if args.install_main_branch:
        success = install_from_main_branch_fn(io)
        analytics.event("exit", reason="Installed main branch")
        return 0 if success else 1

    if args.upgrade:
        success = install_upgrade_fn(io)
        analytics.event("exit", reason="Upgrade completed")
        return 0 if success else 1

    if args.check_update:
        check_version_fn(io, verbose=args.verbose)

    return None


def handle_gui_flow(args, io, analytics, return_coder=False, launch_gui_fn=None):
    """Handle GUI-specific flow."""
    if args.gui and not return_coder:
        if not check_streamlit_install(io):
            analytics.event("exit", reason="Streamlit not installed")
            return 1
        analytics.event("gui session")

        if launch_gui_fn is None:
            from aider.bootstrap.gui import launch_gui as launch_gui_fn

        launch_gui_fn(sys.argv)
        analytics.event("exit", reason="GUI session ended")
        return True  # Indicates GUI was handled
    return False  # Indicates GUI was not handled


def handle_shell_completions(parser, args):
    """Handle shell completions."""
    if args.shell_completions:
        import shtab
        parser.prog = "aider"
        print(shtab.complete(parser, shell=args.shell_completions))
        return True
    return False


def handle_ssl_setup(args):
    """Handle SSL verification setup."""
    if not args.verify_ssl:
        import httpx
        from aider import models
        from aider.llm import litellm

        os.environ["SSL_VERIFY"] = ""
        litellm._load_litellm()
        litellm._lazy_module.client_session = httpx.Client(verify=False)
        litellm._lazy_module.aclient_session = httpx.AsyncClient(verify=False)
        models.model_info_manager.set_verify_ssl(False)


def handle_timeout_setup(args):
    """Handle timeout setup."""
    if args.timeout:
        from aider import models

        models.request_timeout = args.timeout


def handle_theme_setup(args):
    """Handle theme (dark/light mode) setup."""
    if args.dark_mode:
        args.user_input_color = "#32FF32"
        args.tool_error_color = "#FF3333"
        args.tool_warning_color = "#FFFF00"
        args.assistant_output_color = "#00FFFF"
        args.code_theme = "monokai"
    elif args.light_mode:
        args.user_input_color = "green"
        args.tool_error_color = "red"
        args.tool_warning_color = "#FFA500"
        args.assistant_output_color = "blue"
        args.code_theme = "default"


def handle_analytics_setup(args, io):
    """Handle analytics setup."""
    from aider import urls
    from aider.analytics import Analytics

    analytics = Analytics(
        logfile=args.analytics_log,
        permanently_disable=args.analytics_disable,
        posthog_host=args.analytics_posthog_host,
        posthog_project_api_key=args.analytics_posthog_project_api_key,
    )
    
    if args.analytics is not False:
        if analytics.need_to_ask(args.analytics):
            io.tool_output(
                "Aider respects your privacy and never collects your code, chat messages, keys or"
                " personal info."
            )
            io.tool_output(f"For more info: {urls.analytics}")
            disable = not io.confirm_ask(
                "Allow collection of anonymous analytics to help improve aider?"
            )
            analytics.asked_opt_in = True
            if disable:
                analytics.disable(permanently=True)
                io.tool_output("Analytics have been permanently disabled.")
            analytics.save_data()
            io.tool_output()
    
    analytics.event("launched")
    return analytics


def handle_hooks_setup(args, io):
    """Handle hooks manager setup."""
    from aider.hooks import create_hooks_manager

    hooks_manager = None
    if args.hooks_dir or args.enable_skills:
        hooks_manager = create_hooks_manager(io=io, verbose=args.verbose)
        
        if args.hooks_dir:
            num_loaded = hooks_manager.load_hooks_from_directory(args.hooks_dir)
            if args.verbose:
                io.tool_output(f"Loaded {num_loaded} hook files from {args.hooks_dir}")
        
        if args.enable_skills and args.skill_path:
            hooks_manager.load_skills(args.skill_path)
        
        hooks_manager.execute("on_init", args=args, io=io)
    
    return hooks_manager
