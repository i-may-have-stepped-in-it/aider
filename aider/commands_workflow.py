import os
import shlex
import subprocess
from datetime import datetime


class WorkflowCommandsMixin:
    """Git, shell, lint, diff, undo, and editor/report commands."""

    def cmd_commit(self, args=None):
        "Commit edits to the repo made outside the chat (commit message optional)"
        from aider.repo import ANY_GIT_ERROR

        try:
            self.raw_cmd_commit(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete commit: {err}")

    def raw_cmd_commit(self, args=None):
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        if not self.coder.repo.is_dirty():
            self.io.tool_warning("No more changes to commit.")
            return

        commit_message = args.strip() if args else None
        self.coder.repo.commit(message=commit_message, coder=self.coder)

    def cmd_lint(self, args="", fnames=None):
        "Lint and fix in-chat files or all dirty files if none in chat"
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        if not fnames:
            fnames = self.coder.get_inchat_relative_files()

        if not fnames and self.coder.repo:
            fnames = self.coder.repo.get_dirty_files()

        if not fnames:
            self.io.tool_warning("No dirty files to lint.")
            return

        fnames = [self.coder.abs_root_path(fname) for fname in fnames]

        # Track results for summary
        results = {"clean": 0, "errors": 0, "fixed": 0, "skipped": 0}
        lint_coder = None
        
        for fname in fnames:
            rel_fname = self.coder.get_rel_fname(fname)
            try:
                errors = self.coder.linter.lint(fname)
            except FileNotFoundError as err:
                self.io.tool_error(f"Unable to lint {rel_fname}")
                self.io.tool_output(str(err))
                results["skipped"] += 1
                continue

            if not errors:
                results["clean"] += 1
                continue

            results["errors"] += 1
            self.io.tool_output(f"\nLint errors in {rel_fname}:")
            self.io.tool_output("-" * 40)
            self.io.tool_output(errors)
            
            # Estimate error count (rough heuristic)
            error_lines = [l for l in errors.split('\n') if l.strip() and not l.startswith(' ')]
            self.io.tool_output(f"\nFound {len(error_lines)} issue(s)")
            
            if not self.io.confirm_ask(f"Fix lint errors in {rel_fname}?", default="y"):
                results["skipped"] += 1
                continue

            if self.coder.repo.is_dirty() and self.coder.dirty_commits:
                self.cmd_commit("")

            if not lint_coder:
                lint_coder = self.coder.clone(
                    cur_messages=[],
                    done_messages=[],
                    fnames=None,
                )

            lint_coder.add_rel_fname(fname)
            lint_coder.run(errors)
            lint_coder.abs_fnames = set()
            results["fixed"] += 1
        
        # Summary
        self.io.tool_output("\n" + "=" * 40)
        self.io.tool_output("Lint Summary:")
        self.io.tool_output(f"  Clean: {results['clean']} files")
        if results['errors'] > 0:
            self.io.tool_output(f"  With errors: {results['errors']} files")
        if results['fixed'] > 0:
            self.io.tool_output(f"  Fixed: {results['fixed']} files")
        if results['skipped'] > 0:
            self.io.tool_output(f"  Skipped: {results['skipped']} files")

        if lint_coder and self.coder.repo.is_dirty() and self.coder.auto_commits:
            self.cmd_commit("")

    def cmd_undo(self, args):
        "Undo the last git commit if it was done by aider"
        from aider.repo import ANY_GIT_ERROR

        try:
            self.raw_cmd_undo(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete undo: {err}")

    def raw_cmd_undo(self, args):
        from aider import prompts
        from aider.repo import ANY_GIT_ERROR

        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        last_commit = self.coder.repo.get_head_commit()
        if not last_commit or not last_commit.parents:
            self.io.tool_error("This is the first commit in the repository. Cannot undo.")
            return

        last_commit_hash = self.coder.repo.get_head_commit_sha(short=True)
        last_commit_message = self.coder.repo.get_head_commit_message("(unknown)").strip()
        last_commit_message = (last_commit_message.splitlines() or [""])[0]
        if last_commit_hash not in self.coder.aider_commit_hashes:
            self.io.tool_error("The last commit was not made by aider in this chat session.")
            self.io.tool_output(
                "You could try `/git reset --hard HEAD^` but be aware that this is a destructive"
                " command!"
            )
            return

        if len(last_commit.parents) > 1:
            self.io.tool_error(
                f"The last commit {last_commit.hexsha} has more than 1 parent, can't undo."
            )
            return

        prev_commit = last_commit.parents[0]
        changed_files_last_commit = [item.a_path for item in last_commit.diff(prev_commit)]

        for fname in changed_files_last_commit:
            if self.coder.repo.repo.is_dirty(path=fname):
                self.io.tool_error(
                    f"The file {fname} has uncommitted changes. Please stash them before undoing."
                )
                return

            try:
                prev_commit.tree[fname]
            except KeyError:
                self.io.tool_error(
                    f"The file {fname} was not in the repository in the previous commit. Cannot"
                    " undo safely."
                )
                return

        local_head = self.coder.repo.repo.git.rev_parse("HEAD")
        current_branch = self.coder.repo.repo.active_branch.name
        try:
            remote_head = self.coder.repo.repo.git.rev_parse(f"origin/{current_branch}")
            has_origin = True
        except ANY_GIT_ERROR:
            has_origin = False

        if has_origin and local_head == remote_head:
            self.io.tool_error(
                "The last commit has already been pushed to the origin. Undoing is not possible."
            )
            return

        # Confirmation prompt
        args_clean = args.strip().lower()
        if args_clean not in ("--force", "-f"):
            # Show files that will be affected
            self.io.tool_output(f"Files to be restored ({len(changed_files_last_commit)}):")
            for fpath in changed_files_last_commit[:5]:
                self.io.tool_output(f"  {fpath}")
            if len(changed_files_last_commit) > 5:
                self.io.tool_output(f"  ... and {len(changed_files_last_commit) - 5} more")
            
            if not self.io.confirm_ask(
                f"Undo commit {last_commit_hash}: {last_commit_message}?",
                default="n",
            ):
                self.io.tool_output("Undo cancelled.")
                return

        restored = set()
        unrestored = set()
        for file_path in changed_files_last_commit:
            try:
                self.coder.repo.repo.git.checkout("HEAD~1", file_path)
                restored.add(file_path)
            except ANY_GIT_ERROR:
                unrestored.add(file_path)

        if unrestored:
            self.io.tool_error(f"Error restoring {file_path}, aborting undo.")
            self.io.tool_output("Restored files:")
            for file in restored:
                self.io.tool_output(f"  {file}")
            self.io.tool_output("Unable to restore files:")
            for file in unrestored:
                self.io.tool_output(f"  {file}")
            return

        self.coder.repo.repo.git.reset("--soft", "HEAD~1")

        self.io.tool_output(f"Removed: {last_commit_hash} {last_commit_message}")

        current_head_hash = self.coder.repo.get_head_commit_sha(short=True)
        current_head_message = self.coder.repo.get_head_commit_message("(unknown)").strip()
        current_head_message = (current_head_message.splitlines() or [""])[0]
        self.io.tool_output(f"Now at:  {current_head_hash} {current_head_message}")

        if self.coder.main_model.send_undo_reply:
            return prompts.undo_command_reply

    def cmd_diff(self, args=""):
        "Display the diff of changes since the last message"
        from aider.repo import ANY_GIT_ERROR

        try:
            self.raw_cmd_diff(args)
        except ANY_GIT_ERROR as err:
            self.io.tool_error(f"Unable to complete diff: {err}")

    def raw_cmd_diff(self, args=""):
        from aider.run_cmd import run_cmd

        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return

        current_head = self.coder.repo.get_head_commit_sha()
        if current_head is None:
            self.io.tool_error("Unable to get current commit. The repository might be empty.")
            return

        if len(self.coder.commit_before_message) < 2:
            commit_before_message = current_head + "^"
        else:
            commit_before_message = self.coder.commit_before_message[-2]

        if not commit_before_message or commit_before_message == current_head:
            self.io.tool_warning("No changes to display since the last message.")
            return

        self.io.tool_output(f"Diff since {commit_before_message[:7]}...")

        if self.coder.pretty:
            run_cmd(f"git diff {commit_before_message}")
            return

        diff = self.coder.repo.diff_commits(
            self.coder.pretty,
            commit_before_message,
            "HEAD",
        )
        self.io.print(diff)

    def cmd_git(self, args):
        "Run a git command (output excluded from chat)"
        combined_output = None
        if not args.strip():
            self.show_command_usage("/git", error="Please provide a git command to run.")
            return
        try:
            parsed_args = self.parse_shell_like_args(args, command_name="/git")
            if parsed_args is None:
                return
            cmd_parts = ["git"] + parsed_args
            env = dict(subprocess.os.environ)
            env["GIT_EDITOR"] = "true"
            result = subprocess.run(
                cmd_parts,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                shell=False,
                encoding=self.io.encoding,
                errors="replace",
            )
            combined_output = result.stdout
        except Exception as e:
            self.io.tool_error(f"Error running /git command: {e}")

        if combined_output is None:
            return
        self.io.tool_output(combined_output)

    def cmd_gs(self, args):
        "Run git status (output excluded from chat)"
        # If user provides args, use them; otherwise default to "status"
        if args.strip():
            return self.cmd_git(f"status {args}")
        return self.cmd_git("status")

    def cmd_gd(self, args):
        "Run git diff (output excluded from chat)"
        # If user provides args, use them; otherwise default to "diff"
        if args.strip():
            return self.cmd_git(f"diff {args}")
        return self.cmd_git("diff")

    def cmd_install_hook(self, args):
        "Install git pre-commit hook to block commits with AI! comments"
        if not self.coder.repo:
            self.io.tool_error("No git repository found. Hooks can only be installed in git repos.")
            return
        
        force = args.strip() == "--force"
        success, message = self.coder.repo.install_ai_comment_hook(force=force)
        if success:
            self.io.tool_output(message)
        else:
            self.io.tool_error(message)

    def cmd_uninstall_hook(self, args):
        "Remove the git pre-commit hook that blocks AI! comments"
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return
        
        success, message = self.coder.repo.remove_ai_comment_hook()
        if success:
            self.io.tool_output(message)
        else:
            self.io.tool_error(message)

    def cmd_blame(self, args):
        "Show git blame for a file (last N lines, default 10)"
        import shlex
        
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return
        
        parts = shlex.split(args.strip())
        n_lines = 10
        filename = None
        
        # Parse arguments
        if len(parts) >= 2 and parts[0] == "-n":
            try:
                n_lines = int(parts[1])
                filename = parts[2] if len(parts) > 2 else None
            except (ValueError, IndexError):
                self.io.tool_error("Usage: /blame [-n N] <filename>")
                return
        elif parts:
            filename = parts[0]
        
        if not filename:
            self.show_command_usage("/blame", error="Usage: /blame [-n N] <filename>")
            return
        
        # Find the file in chat or repo
        abs_path = None
        for fname in self.coder.abs_fnames:
            if self.coder.get_rel_fname(fname) == filename or fname.endswith(filename):
                abs_path = fname
                break
        
        if not abs_path:
            # Try as relative path
            abs_path = self.coder.abs_root_path(filename)
            if not Path(abs_path).exists():
                self.io.tool_error(f"File not found: {filename}")
                return
        
        # Check if binary
        try:
            with open(abs_path, 'rb') as f:
                chunk = f.read(1024)
                if b'\x00' in chunk:
                    self.io.tool_error(f"Cannot show blame for binary file: {filename}")
                    return
        except Exception:
            pass
        
        try:
            import subprocess
            result = subprocess.run(
                ["git", "-C", self.coder.root, "blame", "-L", f"-{n_lines},", abs_path],
                capture_output=True,
                text=True,
                encoding=self.io.encoding
            )
            
            if result.returncode == 0:
                self.io.tool_output(f"Last {n_lines} lines of {filename}:")
                self.io.tool_output("-" * 40)
                self.io.tool_output(result.stdout)
            else:
                self.io.tool_error(f"Could not get blame info: {result.stderr}")
                
        except Exception as e:
            self.io.tool_error(f"Error: {e}")

    def cmd_checkpoint(self, args):
        "Create or restore git checkpoints (stashes)"
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return
        
        import subprocess
        args_clean = args.strip().lower()
        
        if args_clean == "list":
            # List checkpoints
            result = subprocess.run(
                ["git", "-C", self.coder.root, "stash", "list"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                self.io.tool_output("Checkpoints (stashes):")
                self.io.tool_output("-" * 40)
                for line in result.stdout.strip().split('\n')[:10]:
                    if 'aider-checkpoint' in line:
                        self.io.tool_output(line)
            else:
                self.io.tool_output("No checkpoints found.")
            return
        
        if args_clean.startswith("restore "):
            # Restore a checkpoint
            stash_ref = args[8:].strip()
            if not stash_ref.startswith("stash@{"):
                stash_ref = f"stash@{{{stash_ref}}}"
            
            result = subprocess.run(
                ["git", "-C", self.coder.root, "stash", "pop", stash_ref],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                self.io.tool_output(f"Restored checkpoint: {stash_ref}")
            else:
                self.io.tool_error(f"Restore failed: {result.stderr}")
            return
        
        # Create checkpoint
        message = args.strip() or f"Checkpoint at {datetime.now().strftime('%H:%M:%S')}"
        
        try:
            result = subprocess.run(
                ["git", "-C", self.coder.root, "stash", "push", "-m", f"aider-checkpoint: {message}"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                self.io.tool_output(f"Checkpoint created: {message}")
                self.io.tool_output("Use '/checkpoint list' to see all, '/checkpoint restore <n>' to restore.")
            else:
                self.io.tool_error(f"Checkpoint failed: {result.stderr}")
                
        except Exception as e:
            self.io.tool_error(f"Error: {e}")

    def cmd_merge(self, args):
        "Check for merge conflicts and resolution suggestions"
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return
        
        try:
            # Check for merge markers
            import subprocess
            result = subprocess.run(
                ["git", "-C", self.coder.root, "diff", "--check"],
                capture_output=True,
                text=True
            )
            
            # Search for conflict markers in files
            marker_result = subprocess.run(
                ["grep", "-r", "<<<<<<<", "--include=*", self.coder.root],
                capture_output=True,
                text=True
            )
            
            if marker_result.returncode == 0 and marker_result.stdout:
                self.io.tool_error("Merge conflicts detected!")
                self.io.tool_output("\nFiles with conflicts:")
                
                conflict_files = set()
                for line in marker_result.stdout.split('\n')[:20]:
                    if ':' in line:
                        fname = line.split(':')[0].replace(self.coder.root + '/', '')
                        conflict_files.add(fname)
                
                for fname in conflict_files:
                    in_chat = "✓" if fname in self.coder.get_inchat_relative_files() else " "
                    self.io.tool_output(f"  [{in_chat}] {fname}")
                
                self.io.tool_output("\nResolution options:")
                self.io.tool_output("  1. Edit files to resolve conflicts manually")
                self.io.tool_output("  2. Use 'git checkout --ours <file>' or 'git checkout --theirs <file>'")
                self.io.tool_output("  3. Add resolved files with /add, then /commit")
            else:
                self.io.tool_output("No merge conflicts detected.")
                
                # Check if we're in a merge state
                merge_head = Path(self.coder.root) / ".git" / "MERGE_HEAD"
                if merge_head.exists():
                    self.io.tool_output("\nMerge in progress. Use /commit to complete.")
                
        except Exception as e:
            self.io.tool_error(f"Error checking merge status: {e}")

    def cmd_chatdiff(self, args):
        "Show aider-specific changes (diff of files in chat)"
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return
        
        try:
            # Get list of files currently in the chat
            chat_files = self.coder.abs_fnames | self.coder.abs_read_only_fnames
            
            if not chat_files:
                self.io.tool_output("No files in chat to diff.")
                return
            
            # Get diff specifically for files in chat
            dirty_files = self.coder.repo.get_dirty_files()
            chat_dirty = [f for f in dirty_files if f in chat_files]
            
            if not chat_dirty:
                self.io.tool_output("No changes in files currently in chat.")
                return
            
            self.io.tool_output(f"Changes in {len(chat_dirty)} file(s) in chat:")
            self.io.tool_output("-" * 40)
            
            for fname in sorted(chat_dirty):
                rel_path = self.coder.get_rel_fname(fname)
                self.io.tool_output(f"\n--- {rel_path} ---")
                diff = self.coder.repo.get_diffs([fname])
                if diff:
                    self.io.tool_output(diff)
                else:
                    self.io.tool_output("(new file or binary)")
                    
        except Exception as e:
            self.io.tool_error(f"Error getting diff: {e}")

    def cmd_test(self, args):
        "Run a shell command and add the output to the chat on non-zero exit code"
        # Handle --history flag
        args_clean = args.strip().lower()
        if args_clean == "--history":
            history = getattr(self.coder, '_test_history', [])
            if not history:
                self.io.tool_output("No test runs recorded yet.")
                return
            
            from datetime import datetime
            self.io.tool_output("Recent test runs:")
            self.io.tool_output("-" * 50)
            for i, (cmd, passed, timestamp) in enumerate(history[-10:], 1):
                status = "PASS" if passed else "FAIL"
                time_str = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
                self.io.tool_output(f"{i}. [{status}] {time_str} {cmd[:40]}")
            return
        
        if not args and self.coder.test_cmd:
            args = self.coder.test_cmd

        if not args:
            self.io.tool_output("Usage: /test <command> or set test_cmd in config")
            return

        if not callable(args):
            if type(args) is not str:
                raise ValueError(repr(args))
            result = self.cmd_run(args, True)
            
            # Track test history
            if not hasattr(self.coder, '_test_history'):
                self.coder._test_history = []
            
            import time
            from datetime import datetime
            passed = result is None  # cmd_run returns None on success
            self.coder._test_history.append((args, passed, time.time()))
            
            # Keep only last 50
            self.coder._test_history = self.coder._test_history[-50:]
            
            return result

        errors = args()
        if not errors:
            return

        self.io.tool_output(errors)
        return errors

    def cmd_shell(self, args):
        "Run an interactive shell (exit to return to aider)"
        shell = os.environ.get("SHELL", "/bin/bash")
        shell_name = os.path.basename(shell)

        self.io.tool_output(
            f"Spawning interactive {shell_name} shell. Type 'exit' to return to aider."
        )
        self.io.tool_output("")

        env = dict(os.environ)
        env["PS1"] = "(aider-shell) $ "
        env["PS2"] = "(aider-shell) > "

        if args.strip():
            result = subprocess.run(
                [shell, "-c", args],
                cwd=self.coder.root,
                env=env,
                encoding=self.io.encoding,
                errors="replace",
            )
        else:
            result = subprocess.run(
                [shell],
                cwd=self.coder.root,
                env=env,
                encoding=self.io.encoding,
                errors="replace",
            )

        self.io.tool_output("")
        self.io.tool_output(f"Exited {shell_name} shell (exit code: {result.returncode})")
        self.io.tool_output("Type a message to continue chatting with aider.")

    def cmd_run(self, args, add_on_nonzero_exit=False):
        "Run a shell command and optionally add the output to the chat (alias: !)"
        from aider import prompts
        from aider.run_cmd import run_cmd

        if not args.strip():
            self.show_command_usage("/run", error="Please provide a shell command to run.")
            return

        exit_status, combined_output = run_cmd(
            args, verbose=self.verbose, error_print=self.io.tool_error, cwd=self.coder.root
        )

        if combined_output is None:
            return

        token_count = self.coder.main_model.token_count(combined_output)
        k_tokens = token_count / 1000

        if add_on_nonzero_exit:
            add = exit_status != 0
        else:
            add = self.io.confirm_ask(f"Add {k_tokens:.1f}k tokens of command output to the chat?")

        if add:
            num_lines = len(combined_output.strip().splitlines())
            line_plural = "line" if num_lines == 1 else "lines"
            self.io.tool_output(f"Added {num_lines} {line_plural} of output to the chat.")

            msg = prompts.run_output.format(
                command=args,
                output=combined_output,
            )

            self.coder.cur_messages += [
                dict(role="user", content=msg),
                dict(role="assistant", content="Ok."),
            ]

            if add_on_nonzero_exit and exit_status != 0:
                return msg
            elif add and exit_status != 0:
                self.io.placeholder = "What's wrong? Fix"

        return None

    def cmd_multiline_mode(self, args):
        "Toggle multiline mode (swaps behavior of Enter and Meta+Enter)"
        self.io.toggle_multiline_mode()

    def cmd_copy(self, args):
        "Copy the last assistant message to the clipboard"
        import pyperclip

        all_messages = self.coder.done_messages + self.coder.cur_messages
        assistant_messages = [msg for msg in reversed(all_messages) if msg["role"] == "assistant"]

        if not assistant_messages:
            self.io.tool_error("No assistant messages found to copy.")
            return

        last_assistant_message = assistant_messages[0]["content"]

        try:
            pyperclip.copy(last_assistant_message)
            preview = (
                last_assistant_message[:50] + "..."
                if len(last_assistant_message) > 50
                else last_assistant_message
            )
            self.io.tool_output(f"Copied last assistant message to clipboard. Preview: {preview}")
        except pyperclip.PyperclipException as e:
            self.io.tool_error(f"Failed to copy to clipboard: {str(e)}")
            self.io.tool_output(
                "You may need to install xclip or xsel on Linux, or pbcopy on macOS."
            )
        except Exception as e:
            self.io.tool_error(f"An unexpected error occurred while copying to clipboard: {str(e)}")

    def cmd_report(self, args):
        "Report a problem by opening a GitHub Issue"
        from aider.report import report_github_issue

        announcements = "\n".join(self.coder.get_announcements())
        issue_text = announcements
        title = args.strip() if args.strip() else None
        report_github_issue(issue_text, title=title, confirm=False)

    def cmd_editor(self, initial_content=""):
        "Open an editor to write a prompt"
        from aider.editor import pipe_editor

        user_input = pipe_editor(initial_content, suffix="md", editor=self.editor)
        if user_input.strip():
            self.io.set_placeholder(user_input.rstrip())

    def cmd_edit(self, args=""):
        "Alias for /editor: Open an editor to write a prompt"
        return self.cmd_editor(args)
