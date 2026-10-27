"""
Launch/bootstrap helpers extracted from aider.main.
"""

import json
import os
import re
import sys
import threading
import traceback
from dataclasses import fields
from pathlib import Path

import importlib_resources  # noqa: F401

try:
    import git
except ImportError:
    git = None

from aider import __version__


def check_config_files_for_yes(config_files):
    found = False
    for config_file in config_files:
        if Path(config_file).exists():
            try:
                with open(config_file, "r") as f:
                    for line in f:
                        if line.strip().startswith("yes:"):
                            print("Configuration error detected.")
                            print(f"The file {config_file} contains a line starting with 'yes:'")
                            print("Please replace 'yes:' with 'yes-always:' in this file.")
                            found = True
            except Exception:
                pass
    return found


def get_git_root():
    """Try and guess the git repo, since the conf.yml can be at the repo root"""
    try:
        repo = git.Repo(search_parent_directories=True)
        return repo.working_tree_dir
    except (git.InvalidGitRepositoryError, FileNotFoundError):
        return None


def guessed_wrong_repo(io, git_root, fnames, git_dname):
    """After we parse the args, we can determine the real repo. Did we guess wrong?"""
    from aider.repo import ANY_GIT_ERROR, GitRepo

    try:
        check_repo = Path(GitRepo(io, fnames, git_dname).root).resolve()
    except (OSError,) + ANY_GIT_ERROR:
        return

    # we had no guess, rely on the "true" repo result
    if not git_root:
        return str(check_repo)

    git_root = Path(git_root).resolve()
    if check_repo == git_root:
        return

    return str(check_repo)


def make_new_repo(git_root, io):
    from aider.repo import ANY_GIT_ERROR

    try:
        repo = git.Repo.init(git_root)
        check_gitignore(git_root, io, False)
    except ANY_GIT_ERROR as err:  # issue #1233
        io.tool_error(f"Unable to create git repo in {git_root}")
        io.tool_output(str(err))
        return

    io.tool_output(f"Git repository created in {git_root}")
    return repo


def setup_git(git_root, io):
    from aider.repo import ANY_GIT_ERROR
    if git is None:
        return

    try:
        cwd = Path.cwd()
    except OSError:
        cwd = None

    repo = None

    if git_root:
        try:
            repo = git.Repo(git_root)
        except ANY_GIT_ERROR:
            pass
    elif cwd == Path.home():
        io.tool_warning(
            "You should probably run aider in your project's directory, not your home dir."
        )
        return
    elif cwd and io.confirm_ask(
        "No git repo found, create one to track aider's changes (recommended)?"
    ):
        git_root = str(cwd.resolve())
        repo = make_new_repo(git_root, io)

    if not repo:
        return

    try:
        user_name = repo.git.config("--get", "user.name") or None
    except git.exc.GitCommandError:
        user_name = None

    try:
        user_email = repo.git.config("--get", "user.email") or None
    except git.exc.GitCommandError:
        user_email = None

    if user_name and user_email:
        return repo.working_tree_dir

    with repo.config_writer() as git_config:
        if not user_name:
            git_config.set_value("user", "name", "Your Name")
            io.tool_warning('Update git name with: git config user.name "Your Name"')
        if not user_email:
            git_config.set_value("user", "email", "you@example.com")
            io.tool_warning('Update git email with: git config user.email "you@example.com"')

    return repo.working_tree_dir


def check_gitignore(git_root, io, ask=True):
    from aider.repo import ANY_GIT_ERROR

    if not git_root:
        return

    try:
        repo = git.Repo(git_root)
        patterns_to_add = []

        if not repo.ignored(".aider"):
            patterns_to_add.append(".aider*")

        env_path = Path(git_root) / ".env"
        if env_path.exists() and not repo.ignored(".env"):
            patterns_to_add.append(".env")

        if not patterns_to_add:
            return

        gitignore_file = Path(git_root) / ".gitignore"
        if gitignore_file.exists():
            try:
                content = io.read_text(gitignore_file)
                if content is None:
                    return
                if not content.endswith("\n"):
                    content += "\n"
            except OSError as e:
                io.tool_error(f"Error when trying to read {gitignore_file}: {e}")
                return
        else:
            content = ""
    except ANY_GIT_ERROR:
        return

    if ask:
        io.tool_output("You can skip this check with --no-gitignore")
        if not io.confirm_ask(f"Add {', '.join(patterns_to_add)} to .gitignore (recommended)?"):
            return

    content += "\n".join(patterns_to_add) + "\n"

    try:
        io.write_text(gitignore_file, content)
        io.tool_output(f"Added {', '.join(patterns_to_add)} to .gitignore")
    except OSError as e:
        io.tool_error(f"Error when trying to write to {gitignore_file}: {e}")
        io.tool_output(
            "Try running with appropriate permissions or manually add these patterns to .gitignore:"
        )
        for pattern in patterns_to_add:
            io.tool_output(f"  {pattern}")


def check_streamlit_install(io):
    from aider import utils

    return utils.check_pip_install_extra(
        io,
        "streamlit",
        "You need to install the aider browser feature",
        ["aider-chat[browser]"],
    )


def parse_lint_cmds(lint_cmds, io):
    err = False
    res = dict()
    for lint_cmd in lint_cmds:
        if re.match(r"^[a-z]+:.*", lint_cmd):
            pieces = lint_cmd.split(":")
            lang = pieces[0]
            cmd = lint_cmd[len(lang) + 1 :]
            lang = lang.strip()
        else:
            lang = None
            cmd = lint_cmd

        cmd = cmd.strip()

        if cmd:
            res[lang] = cmd
        else:
            io.tool_error(f'Unable to parse --lint-cmd "{lint_cmd}"')
            io.tool_output('The arg should be "language: cmd --args ..."')
            io.tool_output('For example: --lint-cmd "python: flake8 --select=E9"')
            err = True
    if err:
        return
    return res


def prepare_main_model(args, argv, io, analytics, git_root):
    """Prepare model aliases, selection, settings, and lint commands."""
    from aider import models, urls
    from aider.models import ModelSettings
    from aider.onboarding import offer_openrouter_oauth, select_default_model

    register_models(git_root, args.model_settings_file, io, verbose=args.verbose)
    register_litellm_models(git_root, args.model_metadata_file, io, verbose=args.verbose)

    if args.list_models:
        models.print_matching_models(io, args.list_models)
        analytics.event("exit", reason="Listed models")
        return True, 0, None, None

    if args.alias:
        for alias_def in args.alias:
            parts = alias_def.split(":", 1)
            if len(parts) != 2:
                io.tool_error(f"Invalid alias format: {alias_def}")
                io.tool_output("Format should be: alias:model-name")
                analytics.event("exit", reason="Invalid alias format error")
                return True, 1, None, None
            alias, model = parts
            models.MODEL_ALIASES[alias.strip()] = model.strip()

    model_explicit = bool(args.model) or any(
        arg == "--model" or arg.startswith("--model=") for arg in argv
    )
    selected_model_name = select_default_model(
        args,
        io,
        analytics,
        model_explicit=model_explicit,
    )
    if not selected_model_name:
        return True, 1, None, None
    args.model = selected_model_name

    if args.model.startswith("openrouter/") and not os.environ.get("OPENROUTER_API_KEY"):
        io.tool_warning(
            f"The specified model '{args.model}' requires an OpenRouter API key, which was not"
            " found."
        )
        if offer_openrouter_oauth(io, analytics):
            if os.environ.get("OPENROUTER_API_KEY"):
                io.tool_output("OpenRouter successfully connected.")
            else:
                io.tool_error(
                    "OpenRouter authentication seemed successful, but the key is still missing."
                )
                analytics.event(
                    "exit",
                    reason="OpenRouter key missing after successful OAuth for specified model",
                )
                return True, 1, None, None
        else:
            io.tool_error(
                f"Unable to proceed without an OpenRouter API key for model '{args.model}'."
            )
            io.offer_url(urls.models_and_keys, "Open documentation URL for more info?")
            analytics.event(
                "exit",
                reason="OpenRouter key missing for specified model and OAuth failed/declined",
            )
            return True, 1, None, None

    main_model = models.Model(
        args.model,
        weak_model=args.weak_model,
        editor_model=args.editor_model,
        editor_edit_format=args.editor_edit_format,
        verbose=args.verbose,
    )

    if main_model.remove_reasoning is not None:
        io.tool_warning(
            "Model setting 'remove_reasoning' is deprecated, please use 'reasoning_tag' instead."
        )

    if args.reasoning_effort is not None:
        if not args.check_model_accepts_settings or (
            main_model.accepts_settings and "reasoning_effort" in main_model.accepts_settings
        ):
            main_model.set_reasoning_effort(args.reasoning_effort)

    if args.thinking_tokens is not None:
        if not args.check_model_accepts_settings or (
            main_model.accepts_settings and "thinking_tokens" in main_model.accepts_settings
        ):
            main_model.set_thinking_tokens(args.thinking_tokens)

    if args.check_model_accepts_settings:
        # Only warn about values the user chose; the built-in defaults apply to every
        # model, so warning about them would just be noise for non-reasoning models.
        settings_to_check = [
            {"arg": args.reasoning_effort, "name": "reasoning_effort", "default": "medium"},
            {"arg": args.thinking_tokens, "name": "thinking_tokens", "default": "4096"},
        ]

        for setting in settings_to_check:
            if setting["arg"] is not None and setting["arg"] != setting["default"] and (
                not main_model.accepts_settings
                or setting["name"] not in main_model.accepts_settings
            ):
                io.tool_warning(
                    f"Warning: {main_model.name} does not support '{setting['name']}', ignoring."
                )
                io.tool_output(
                    f"Use --no-check-model-accepts-settings to force the '{setting['name']}'"
                    " setting."
                )

    if args.copy_paste and args.edit_format is None:
        if main_model.edit_format in ("diff", "whole", "diff-fenced"):
            main_model.edit_format = "editor-" + main_model.edit_format

    if args.verbose:
        io.tool_output("Model metadata:")
        io.tool_output(json.dumps(main_model.info, indent=4))

        io.tool_output("Model settings:")
        for attr in sorted(fields(ModelSettings), key=lambda x: x.name):
            val = getattr(main_model, attr.name)
            val = json.dumps(val, indent=4)
            io.tool_output(f"{attr.name}: {val}")

    lint_cmds = parse_lint_cmds(args.lint_cmd, io)
    if lint_cmds is None:
        analytics.event("exit", reason="Invalid lint command format")
        return True, 1, None, None

    if args.show_model_warnings and not args.exit:
        problem = models.sanity_check_models(io, main_model)
        if problem:
            analytics.event("model warning", main_model=main_model)
            io.tool_output("You can skip this check with --no-show-model-warnings")

            try:
                io.offer_url(urls.model_warnings, "Open documentation url for more info?")
                io.tool_output()
            except KeyboardInterrupt:
                analytics.event("exit", reason="Keyboard interrupt during model warnings")
                return True, 1, None, None

    return False, None, main_model, lint_cmds


def apply_env_and_deprecated_args(args, io):
    """Apply env-var, API-key, and deprecated model argument side effects."""
    from aider.deprecated import handle_deprecated_model_args

    if args.set_env:
        for env_setting in args.set_env:
            try:
                name, value = env_setting.split("=", 1)
                os.environ[name.strip()] = value.strip()
            except ValueError:
                io.tool_error(f"Invalid --set-env format: {env_setting}")
                io.tool_output("Format should be: ENV_VAR_NAME=value")
                return 1

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

    if getattr(args, "venice_api_key", None):
        os.environ["VENICE_API_KEY"] = args.venice_api_key

    from aider import venice

    if getattr(args, "venice_character", None):
        venice.runtime["character"] = args.venice_character
    if getattr(args, "venice_web_search", None):
        venice.runtime["web_search"] = args.venice_web_search

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

    return None


def prepare_repo_and_runtime(args, io, analytics, hooks_manager, main_model, fnames, git_dname):
    """Create the git repo wrapper if enabled and assemble the session runtime."""
    from aider.repo import GitRepo
    from aider.session_runtime import SessionRuntime

    repo = None
    if args.git:
        try:
            repo = GitRepo(
                io,
                fnames,
                git_dname,
                args.aiderignore,
                models=main_model.commit_message_models(),
                attribute_author=args.attribute_author,
                attribute_committer=args.attribute_committer,
                attribute_commit_message_author=args.attribute_commit_message_author,
                attribute_commit_message_committer=args.attribute_commit_message_committer,
                commit_prompt=args.commit_prompt,
                subtree_only=args.subtree_only,
                git_commit_verify=args.git_commit_verify,
                attribute_co_authored_by=args.attribute_co_authored_by,
            )
        except FileNotFoundError:
            pass

    if not args.skip_sanity_check_repo:
        if not sanity_check_repo(repo, io):
            analytics.event("exit", reason="Repository sanity check failed")
            return True, 1, None, None

    if repo and not args.skip_sanity_check_repo:
        num_files = len(repo.get_tracked_files())
        analytics.event("repo", num_files=num_files)
    else:
        analytics.event("no-repo")

    runtime = SessionRuntime.create(
        io=io,
        analytics=analytics,
        hooks_manager=hooks_manager,
        resolve_defaults=False,
        max_budget=getattr(args, 'budget', None) or 5.0,
    )
    return False, None, repo, runtime


def should_preload_imports(args, return_coder=False):
    return not any(
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
    )


def should_background_semantic_index(args, return_coder=False):
    return not any(
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
    )


def generate_search_path_list(default_file, git_root, command_line_file):
    files = []
    files.append(Path.home() / default_file)  # homedir
    if git_root:
        files.append(Path(git_root) / default_file)  # git root
    files.append(default_file)
    if command_line_file:
        files.append(command_line_file)

    resolved_files = []
    for fn in files:
        try:
            resolved_files.append(Path(fn).resolve())
        except OSError:
            pass

    files = resolved_files
    files.reverse()
    uniq = []
    for fn in files:
        if fn not in uniq:
            uniq.append(fn)
    uniq.reverse()
    files = uniq
    files = list(map(str, files))
    files = list(dict.fromkeys(files))

    return files


def register_models(git_root, model_settings_fname, io, verbose=False):
    from aider import models

    model_settings_files = generate_search_path_list(
        ".aider.model.settings.yml", git_root, model_settings_fname
    )

    try:
        files_loaded = models.register_models(model_settings_files)
        if len(files_loaded) > 0:
            if verbose:
                io.tool_output("Loaded model settings from:")
                for file_loaded in files_loaded:
                    io.tool_output(f"  - {file_loaded}")  # noqa: E221
        elif verbose:
            io.tool_output("No model settings files loaded")
    except Exception as e:
        io.tool_error(f"Error loading aider model settings: {e}")
        return 1

    if verbose:
        io.tool_output("Searched for model settings files:")
        for file in model_settings_files:
            io.tool_output(f"  - {file}")

    return None


def load_dotenv_files(git_root, dotenv_fname, encoding="utf-8"):
    from dotenv import load_dotenv

    # Standard .env file search path
    dotenv_files = generate_search_path_list(
        ".env",
        git_root,
        dotenv_fname,
    )

    # Explicitly add the OAuth keys file to the beginning of the list
    oauth_keys_file = Path.home() / ".aider" / "oauth-keys.env"
    if oauth_keys_file.exists():
        # Insert at the beginning so it's loaded first (and potentially overridden)
        dotenv_files.insert(0, str(oauth_keys_file.resolve()))
        # Remove duplicates if it somehow got included by generate_search_path_list
        dotenv_files = list(dict.fromkeys(dotenv_files))

    loaded = []
    for fname in dotenv_files:
        try:
            if Path(fname).exists():
                load_dotenv(fname, override=True, encoding=encoding)
                loaded.append(fname)
        except OSError as e:
            print(f"OSError loading {fname}: {e}")
        except Exception as e:
            print(f"Error loading {fname}: {e}")
    return loaded


def register_litellm_models(git_root, model_metadata_fname, io, verbose=False):
    from aider import models

    model_metadata_files = []

    # Add the resource file path
    resource_metadata = importlib_resources.files("aider.resources").joinpath("model-metadata.json")
    model_metadata_files.append(str(resource_metadata))

    model_metadata_files += generate_search_path_list(
        ".aider.model.metadata.json", git_root, model_metadata_fname
    )

    try:
        model_metadata_files_loaded = models.register_litellm_models(model_metadata_files)
        if len(model_metadata_files_loaded) > 0 and verbose:
            io.tool_output("Loaded model metadata from:")
            for model_metadata_file in model_metadata_files_loaded:
                io.tool_output(f"  - {model_metadata_file}")  # noqa: E221
    except Exception as e:
        io.tool_error(f"Error loading model metadata models: {e}")
        return 1


def sanity_check_repo(repo, io):
    from aider import urls
    from aider.repo import ANY_GIT_ERROR

    if not repo:
        return True

    if not repo.repo.working_tree_dir:
        io.tool_error("The git repo does not seem to have a working tree?")
        return False

    bad_ver = False
    try:
        repo.get_tracked_files()
        if not repo.git_repo_error:
            return True
        error_msg = str(repo.git_repo_error)
    except UnicodeDecodeError as exc:
        error_msg = (
            "Failed to read the Git repository. This issue is likely caused by a path encoded "
            f'in a format different from the expected encoding "{sys.getfilesystemencoding()}".\n'
            f"Internal error: {str(exc)}"
        )
    except ANY_GIT_ERROR as exc:
        error_msg = str(exc)
        bad_ver = "version in (1, 2)" in error_msg
    except AssertionError as exc:
        error_msg = str(exc)
        bad_ver = True

    if bad_ver:
        io.tool_error("Aider only works with git repos with version number 1 or 2.")
        io.tool_output("You may be able to convert your repo: git update-index --index-version=2")
        io.tool_output("Or run aider --no-git to proceed without using git.")
        io.offer_url(urls.git_index_version, "Open documentation url for more info?")
        return False

    io.tool_error("Unable to read git repository, it may be corrupt?")
    io.tool_output(error_msg)
    return False


def is_first_run_of_new_version(io, verbose=False):
    """Check if this is the first run of a new version/executable combination"""
    installs_file = Path.home() / ".aider" / "installs.json"
    key = (__version__, sys.executable)

    # Never show notes for .dev versions
    if ".dev" in __version__:
        return False

    if verbose:
        io.tool_output(
            f"Checking imports for version {__version__} and executable {sys.executable}"
        )
        io.tool_output(f"Installs file: {installs_file}")

    try:
        if installs_file.exists():
            with open(installs_file, "r") as f:
                installs = json.load(f)
            if verbose:
                io.tool_output("Installs file exists and loaded")
        else:
            installs = {}
            if verbose:
                io.tool_output("Installs file does not exist, creating new dictionary")

        is_first_run = str(key) not in installs

        if is_first_run:
            installs[str(key)] = True
            installs_file.parent.mkdir(parents=True, exist_ok=True)
            with open(installs_file, "w") as f:
                json.dump(installs, f, indent=4)

        return is_first_run

    except Exception as e:
        io.tool_warning(f"Error checking version: {e}")
        if verbose:
            io.tool_output(f"Full exception details: {traceback.format_exc()}")
        return True  # Safer to assume it's a first run if we hit an error


def check_and_load_imports(io, is_first_run, verbose=False):
    from aider import urls

    try:
        if is_first_run:
            if verbose:
                io.tool_output(
                    "First run for this version and executable, loading imports synchronously"
                )
            try:
                load_slow_imports(swallow=False)
            except Exception as err:
                io.tool_error(str(err))
                io.tool_output("Error loading required imports. Did you install aider properly?")
                io.offer_url(urls.install_properly, "Open documentation url for more info?")
                sys.exit(1)

            if verbose:
                io.tool_output("Imports loaded and installs file updated")
        else:
            if verbose:
                io.tool_output("Not first run, loading imports in background thread")
            thread = threading.Thread(target=load_slow_imports)
            thread.daemon = True
            thread.start()

    except Exception as e:
        io.tool_warning(f"Error in loading imports: {e}")
        if verbose:
            io.tool_output(f"Full exception details: {traceback.format_exc()}")


def load_slow_imports(swallow=True):
    # These imports are deferred in various ways to
    # improve startup time.
    # This func is called either synchronously or in a thread
    # depending on whether it's been run before for this version and executable.

    try:
        import httpx  # noqa: F401
        import litellm  # noqa: F401
        import networkx  # noqa: F401
        import numpy  # noqa: F401
    except Exception as e:
        if not swallow:
            raise e


def build_default_config_files(git_root):
    conf_fname = Path(".aider.conf.yml")

    default_config_files = []
    try:
        default_config_files += [conf_fname.resolve()]  # CWD
    except OSError:
        pass

    if git_root:
        git_conf = Path(git_root) / conf_fname  # git root
        if git_conf not in default_config_files:
            default_config_files.append(git_conf)
    default_config_files.append(Path.home() / conf_fname)  # homedir
    return list(map(str, default_config_files))


def parse_args(argv, git_root):
    from aider.args import get_parser

    blank_aider_env = {
        key: value for key, value in os.environ.items()
        if key.startswith("AIDER_") and not value
    }

    for key in blank_aider_env:
        os.environ.pop(key, None)

    try:
        parser = get_parser(build_default_config_files(git_root), git_root)
        try:
            args, unknown = parser.parse_known_args(argv)
        except AttributeError as e:
            words = ["bool", "object", "has", "no", "attribute", "strip"]
            if all(word in str(e) for word in words):
                if check_config_files_for_yes(build_default_config_files(git_root)):
                    return parser, None, None, 1
            raise e

        default_config_files = build_default_config_files(git_root)
        if args.verbose:
            print("Config files search order, if no --config:")
            for file in default_config_files:
                exists = "(exists)" if Path(file).exists() else ""
                print(f"  - {file} {exists}")

        default_config_files.reverse()

        parser = get_parser(default_config_files, git_root)
        args, unknown = parser.parse_known_args(argv)
        loaded_dotenvs = load_dotenv_files(git_root, args.env_file, args.encoding)
        args = parser.parse_args(argv)
        return parser, args, loaded_dotenvs, None
    finally:
        os.environ.update(blank_aider_env)
