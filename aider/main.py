import os
import sys
import webbrowser
from pathlib import Path

try:
    import git
except ImportError:
    git = None

import shtab
from prompt_toolkit.enums import EditingMode

from aider import models, urls, utils
from aider.analytics import Analytics
from aider.bootstrap import launch as launch_bootstrap
from aider.bootstrap.gui import launch_gui
from aider.bootstrap.launch import (
    check_and_load_imports,
    check_gitignore,
    check_streamlit_install,
    get_git_root,
    guessed_wrong_repo,
    is_first_run_of_new_version,
    prepare_main_model,
    prepare_repo_and_runtime,
    setup_git,
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
from aider.deprecated import handle_deprecated_model_args
from aider.format_settings import format_settings, scrub_sensitive_info
from aider.hooks import create_hooks_manager
from aider.io import InputOutput
from aider.llm import litellm  # noqa: F401; properly init litellm on launch
from aider.report import report_uncaught_exceptions
from aider.versioncheck import check_version, install_from_main_branch, install_upgrade

from .dump import dump  # noqa: F401

importlib_resources = launch_bootstrap.importlib_resources
load_dotenv_files = launch_bootstrap.load_dotenv_files


def main(argv=None, input=None, output=None, force_git_root=None, return_coder=False):
    report_uncaught_exceptions()

    if argv is None:
        argv = sys.argv[1:]

    if git is None:
        git_root = None
    elif force_git_root:
        git_root = force_git_root
    else:
        git_root = get_git_root()

    parser, args, loaded_dotenvs, err = launch_bootstrap.parse_args(argv, git_root)
    if err:
        return err

    if args.shell_completions:
        # Ensure parser.prog is set for shtab, though it should be by default
        parser.prog = "aider"
        print(shtab.complete(parser, shell=args.shell_completions))
        sys.exit(0)

    if git is None:
        args.git = False

    if args.analytics_disable:
        analytics = Analytics(permanently_disable=True)
        print("Analytics have been permanently disabled.")

    if not args.verify_ssl:
        import httpx

        os.environ["SSL_VERIFY"] = ""
        litellm._load_litellm()
        litellm._lazy_module.client_session = httpx.Client(verify=False)
        litellm._lazy_module.aclient_session = httpx.AsyncClient(verify=False)
        # Set verify_ssl on the model_info_manager
        models.model_info_manager.set_verify_ssl(False)

    if args.timeout:
        models.request_timeout = args.timeout

    if args.dark_mode:
        args.user_input_color = "#32FF32"
        args.tool_error_color = "#FF3333"
        args.tool_warning_color = "#FFFF00"
        args.assistant_output_color = "#00FFFF"
        args.code_theme = "monokai"

    if args.light_mode:
        args.user_input_color = "green"
        args.tool_error_color = "red"
        args.tool_warning_color = "#FFA500"
        args.assistant_output_color = "blue"
        args.code_theme = "default"

    if return_coder and args.yes_always is None:
        args.yes_always = True

    editing_mode = EditingMode.VI if args.vim else EditingMode.EMACS

    def get_io(pretty):
        return InputOutput(
            pretty,
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
        )

    io = get_io(args.pretty)
    try:
        io.rule()
    except UnicodeEncodeError as err:
        if not io.pretty:
            raise err
        io = get_io(False)
        io.tool_warning("Terminal does not support pretty output (UnicodeDecodeError)")

    # Process any environment variables set via --set-env
    if args.set_env:
        for env_setting in args.set_env:
            try:
                name, value = env_setting.split("=", 1)
                os.environ[name.strip()] = value.strip()
            except ValueError:
                io.tool_error(f"Invalid --set-env format: {env_setting}")
                io.tool_output("Format should be: ENV_VAR_NAME=value")
                return 1

    # Process any API keys set via --api-key
    if args.api_key:
        for api_setting in args.api_key:
            try:
                provider, key = api_setting.split("=", 1)
                env_var = f"{provider.strip().upper()}_API_KEY"
                os.environ[env_var] = key.strip()
            except ValueError:
                io.tool_error(f"Invalid --api-key format: {api_setting}")
                io.tool_output("Format should be: provider=key")
                return 1

    if args.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = args.anthropic_api_key

    if args.openai_api_key:
        os.environ["OPENAI_API_KEY"] = args.openai_api_key

    # Handle deprecated model shortcut args
    handle_deprecated_model_args(args, io)
    if args.openai_api_base:
        os.environ["OPENAI_API_BASE"] = args.openai_api_base
    if args.openai_api_version:
        io.tool_warning(
            "--openai-api-version is deprecated, use --set-env OPENAI_API_VERSION=<value>"
        )
        os.environ["OPENAI_API_VERSION"] = args.openai_api_version
    if args.openai_api_type:
        io.tool_warning("--openai-api-type is deprecated, use --set-env OPENAI_API_TYPE=<value>")
        os.environ["OPENAI_API_TYPE"] = args.openai_api_type
    if args.openai_organization_id:
        io.tool_warning(
            "--openai-organization-id is deprecated, use --set-env OPENAI_ORGANIZATION=<value>"
        )
        os.environ["OPENAI_ORGANIZATION"] = args.openai_organization_id

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

        # This is a no-op if the user has opted out
        analytics.enable()

    analytics.event("launched")

    # Initialize hooks manager
    hooks_manager = None
    if args.hooks_dir or args.enable_skills:
        hooks_manager = create_hooks_manager(io=io, verbose=args.verbose)

        # Load hooks from directory if specified
        if args.hooks_dir:
            num_loaded = hooks_manager.load_hooks_from_directory(args.hooks_dir)
            if args.verbose:
                io.tool_output(f"Loaded {num_loaded} hook files from {args.hooks_dir}")

        # Load skills if enabled
        if args.enable_skills and args.skill_path:
            hooks_manager.load_skills(args.skill_path)

        # Execute on_init hooks
        hooks_manager.execute("on_init", args=args, io=io)

    if args.gui and not return_coder:
        if not check_streamlit_install(io):
            analytics.event("exit", reason="Streamlit not installed")
            return
        analytics.event("gui session")
        launch_gui(argv)
        analytics.event("exit", reason="GUI session ended")
        return

    if args.verbose:
        for fname in loaded_dotenvs:
            io.tool_output(f"Loaded {fname}")

    all_files = args.files + (args.file or [])
    fnames = [str(Path(fn).resolve()) for fn in all_files]
    read_only_fnames = []
    for fn in args.read or []:
        path = Path(fn).expanduser().resolve()
        if path.is_dir():
            read_only_fnames.extend(str(f) for f in path.rglob("*") if f.is_file())
        else:
            read_only_fnames.append(str(path))

    if len(all_files) > 1:
        good = True
        for fname in all_files:
            if Path(fname).is_dir():
                io.tool_error(f"{fname} is a directory, not provided alone.")
                good = False
        if not good:
            io.tool_output(
                "Provide either a single directory of a git repo, or a list of one or more files."
            )
            analytics.event("exit", reason="Invalid directory input")
            return 1

    git_dname = None
    if len(all_files) == 1:
        if Path(all_files[0]).is_dir():
            if args.git:
                git_dname = str(Path(all_files[0]).resolve())
                fnames = []
            else:
                io.tool_error(f"{all_files[0]} is a directory, but --no-git selected.")
                analytics.event("exit", reason="Directory with --no-git")
                return 1

    # We can't know the git repo for sure until after parsing the args.
    # If we guessed wrong, reparse because that changes things like
    # the location of the config.yml and history files.
    if args.git and not force_git_root and git is not None:
        right_repo_root = guessed_wrong_repo(io, git_root, fnames, git_dname)
        if right_repo_root:
            analytics.event("exit", reason="Recursing with correct repo")
            return main(argv, input, output, right_repo_root, return_coder=return_coder)

    if args.just_check_update:
        update_available = check_version(io, just_check=True, verbose=args.verbose)
        analytics.event("exit", reason="Just checking update")
        return 0 if not update_available else 1

    if args.install_main_branch:
        success = install_from_main_branch(io)
        analytics.event("exit", reason="Installed main branch")
        return 0 if success else 1

    if args.upgrade:
        success = install_upgrade(io)
        analytics.event("exit", reason="Upgrade completed")
        return 0 if success else 1

    if args.check_update:
        check_version(io, verbose=args.verbose)

    if args.git:
        git_root = setup_git(git_root, io)
        if args.gitignore:
            check_gitignore(git_root, io)

    if args.verbose:
        show = format_settings(parser, args)
        io.tool_output(show)

    cmd_line = " ".join(sys.argv)
    cmd_line = scrub_sensitive_info(args, cmd_line)
    io.tool_output(cmd_line, log_only=True)

    is_first_run = is_first_run_of_new_version(io, verbose=args.verbose)
    check_and_load_imports(io, is_first_run, verbose=args.verbose)

    handled, result, main_model, lint_cmds = prepare_main_model(
        args=args,
        argv=argv,
        io=io,
        analytics=analytics,
        git_root=git_root,
    )
    if handled:
        return result

    handled, result, repo, runtime = prepare_repo_and_runtime(
        args=args,
        io=io,
        analytics=analytics,
        hooks_manager=hooks_manager,
        main_model=main_model,
        fnames=fnames,
        git_dname=git_dname,
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
        background_semantic_index=not any(
            [
                return_coder,
                args.exit,
                args.message,
                args.message_file,
                args.mcp,
                args.acp,
                args.show_prompts,
                args.lint,
                args.test,
                args.commit,
                args.show_repo_map,
                args.apply,
            ]
        ),
    )
    if isinstance(coder, int):
        return coder

    if return_coder:
        analytics.event("exit", reason="Returning coder object")
        return coder

    attach_runtime_services(args, coder, analytics, git_root, hooks_manager)

    handled, result = handle_pre_run_actions(
        args=args,
        io=io,
        coder=coder,
        commands=commands,
        analytics=analytics,
        main_model=main_model,
        git_root=git_root,
        is_first_run=is_first_run,
        urls_module=urls,
        webbrowser_module=webbrowser,
        utils_module=utils,
        fnames=fnames,
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
