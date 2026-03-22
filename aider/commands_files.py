import glob
import os
import re
from os.path import expanduser
from pathlib import Path

from aider.utils import is_image_file


def _expand_subdir(file_path):
    if file_path.is_file():
        yield file_path
        return

    if file_path.is_dir():
        for file in file_path.rglob("*"):
            if file.is_file():
                yield file


class FileCommandsMixin:
    """File and session state command handlers."""

    def _drop_all_files(self):
        self.coder.abs_fnames = set()

        if self.original_read_only_fnames:
            to_keep = set()
            for abs_fname in self.coder.abs_read_only_fnames:
                rel_fname = self.coder.get_rel_fname(abs_fname)
                if (
                    abs_fname in self.original_read_only_fnames
                    or rel_fname in self.original_read_only_fnames
                ):
                    to_keep.add(abs_fname)
            self.coder.abs_read_only_fnames = to_keep
        else:
            self.coder.abs_read_only_fnames = set()

    def _clear_chat_history(self):
        self.coder.done_messages = []
        self.coder.cur_messages = []

    def cmd_clear(self, args):
        "Clear the chat history"

        self._clear_chat_history()
        self.io.tool_output("All chat history cleared.")

    def cmd_history(self, args):
        "Search or display chat history (use --all to show all)"
        args_clean = args.strip().lower()
        show_all = "--all" in args_clean
        query = args_clean.replace("--all", "").strip()
        
        messages = self.coder.done_messages + self.coder.cur_messages
        
        if not messages:
            self.io.tool_output("No chat history.")
            return
        
        # Count messages by role (skip system for cleaner output)
        user_msgs = sum(1 for m in messages if m.get("role") == "user")
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")
        
        self.io.tool_output(f"Chat history: {user_msgs} user, {assistant_msgs} assistant messages")
        
        if query:
            self.io.tool_output(f"\nSearching for: {query}")
            self.io.tool_output("-" * 40)
            
            matches = []
            for i, msg in enumerate(messages):
                role = msg.get("role", "")
                if role == "system":
                    continue  # Skip system messages in search
                content = msg.get("content", "")
                if isinstance(content, str) and query in content.lower():
                    # Truncate long content
                    preview = content[:200].replace("\n", " ")
                    if len(content) > 200:
                        preview += "..."
                    matches.append((i, role, preview))
            
            if matches:
                self.io.tool_output(f"Found {len(matches)} matches (showing last 10):")
                for idx, role, preview in matches[-10:]:
                    self.io.tool_output(f"\n[{idx}] {role}: {preview}")
                if len(matches) > 10 and not show_all:
                    self.io.tool_output(f"\n... and {len(matches) - 10} more (use --all to show all)")
            else:
                self.io.tool_output("No matches found.")
        else:
            # Show recent messages
            display_msgs = messages if show_all else messages[-20:]
            if not show_all and len(messages) > 20:
                self.io.tool_output(f"\nShowing last 20 messages (use --all for all {len(messages)}):")
            
            for i, msg in enumerate(display_msgs):
                role = msg.get("role", "unknown")
                if role == "system":
                    continue
                content = msg.get("content", "")
                if isinstance(content, str):
                    preview = content[:100].replace("\n", " ")
                    if len(content) > 100:
                        preview += "..."
                    self.io.tool_output(f"[{i}] {role}: {preview}")

    def cmd_rename(self, args):
        "Rename a file in the chat (also renames on disk) using git mv"
        import os
        import subprocess
        from pathlib import Path
        
        parts = args.strip().split()
        if len(parts) != 2:
            self.show_command_usage("/rename", error="Usage: /rename <old> <new>")
            return
        
        old_name, new_name = parts
        
        # Security: Validate new_name doesn't escape repo
        if '..' in new_name or new_name.startswith('/'):
            self.io.tool_error("Invalid new name: path traversal detected")
            return
        
        # Find the file
        old_path = None
        for fname in self.coder.abs_fnames:
            if self.coder.get_rel_fname(fname) == old_name or fname.endswith(old_name):
                old_path = fname
                break
        
        if not old_path:
            self.io.tool_error(f"File not in chat: {old_name}")
            return
        
        # Calculate new path
        old_abs = Path(old_path)
        new_abs = old_abs.parent / new_name
        
        # Check if new name already exists
        if new_abs.exists():
            self.io.tool_error(f"Target already exists: {new_name}")
            return
        
        try:
            # Use git mv if possible
            if self.coder.repo:
                rel_old = self.coder.get_rel_fname(old_path)
                rel_new = str(Path(rel_old).parent / new_name)
                subprocess.run(
                    ["git", "-C", self.coder.root, "mv", rel_old, rel_new],
                    check=True,
                    capture_output=True
                )
            else:
                # Fallback to regular rename
                old_abs.rename(new_abs)
            
            # Update coder's file tracking
            self.coder.abs_fnames.discard(old_path)
            self.coder.abs_fnames.add(str(new_abs))
            
            # Update read-only if needed
            if old_path in self.coder.abs_read_only_fnames:
                self.coder.abs_read_only_fnames.discard(old_path)
                self.coder.abs_read_only_fnames.add(str(new_abs))
            
            self.io.tool_output(f"Renamed: {old_name} -> {new_name}")
            
            # Commit the rename if auto-commits enabled
            if self.coder.auto_commits and self.coder.repo:
                self.coder.repo.commit(
                    message=f"Rename {old_name} to {new_name}",
                    coder=self.coder
                )
                
        except Exception as e:
            self.io.tool_error(f"Rename failed: {e}")

    def cmd_verify(self, args):
        "Verify files in chat are readable and trackable"
        files = list(self.coder.abs_fnames)
        
        if not files:
            self.io.tool_output("No files in chat.")
            return
        
        self.io.tool_output("Verifying files...")
        self.io.tool_output("-" * 50)
        
        ok = 0
        warnings = []
        errors = []
        
        for fname in files:
            rel = self.coder.get_rel_fname(fname)
            
            # Check exists
            if not Path(fname).exists():
                errors.append(f"{rel}: File does not exist")
                continue
            
            # Check readable
            try:
                content = self.io.read_text(fname)
                if content is None:
                    warnings.append(f"{rel}: Could not read content")
            except Exception as e:
                errors.append(f"{rel}: Read error - {e}")
                continue
            
            # Check in git
            if self.coder.repo:
                try:
                    tracked = self.coder.repo.repo.git.ls_files(fname)
                    if not tracked:
                        warnings.append(f"{rel}: Not tracked by git")
                except Exception:
                    warnings.append(f"{rel}: Git check failed")
            
            ok += 1
            self.io.tool_output(f"  ✓ {rel}")
        
        self.io.tool_output("-" * 50)
        self.io.tool_output(f"OK: {ok}/{len(files)}")
        
        if warnings:
            self.io.tool_warning(f"\nWarnings ({len(warnings)}):")
            for w in warnings:
                self.io.tool_output(f"  ⚠ {w}")
        
        if errors:
            self.io.tool_error(f"\nErrors ({len(errors)}):")
            for e in errors:
                self.io.tool_output(f"  ✗ {e}")

    def cmd_backup(self, args):
        "Create a backup of files in chat"
        import shutil
        from datetime import datetime
        
        files = list(self.coder.abs_fnames)
        if not files:
            self.io.tool_output("No files in chat to backup.")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = Path(self.coder.root) / f".aider.backup.{timestamp}"
        
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            backed_up = 0
            
            for fname in files:
                rel_path = self.coder.get_rel_fname(fname)
                dest = backup_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(fname, dest)
                backed_up += 1
            
            self.io.tool_output(f"Backup created: {backup_dir}")
            self.io.tool_output(f"Backed up {backed_up} file(s)")
            
        except Exception as e:
            self.io.tool_error(f"Backup failed: {e}")

    def cmd_compare(self, args):
        "Compare two files side by side"
        import difflib
        
        parts = args.strip().split()
        if len(parts) != 2:
            self.show_command_usage("/compare", error="Usage: /compare <file1> <file2>")
            return
        
        file1, file2 = parts
        
        # Resolve both files
        def resolve_file(name):
            for fname in self.coder.abs_fnames:
                if self.coder.get_rel_fname(fname) == name or fname.endswith(name):
                    return fname
            abs_path = self.coder.abs_root_path(name)
            if Path(abs_path).exists():
                return abs_path
            return None
        
        abs1 = resolve_file(file1)
        abs2 = resolve_file(file2)
        
        if not abs1:
            self.io.tool_error(f"File not found: {file1}")
            return
        if not abs2:
            self.io.tool_error(f"File not found: {file2}")
            return
        
        try:
            content1 = self.io.read_text(abs1) or ""
            content2 = self.io.read_text(abs2) or ""
            
            lines1 = content1.splitlines(keepends=True)
            lines2 = content2.splitlines(keepends=True)
            
            diff = list(difflib.unified_diff(
                lines1, lines2,
                fromfile=file1, tofile=file2,
                lineterm=''
            ))
            
            if diff:
                self.io.tool_output(f"Differences between {file1} and {file2}:")
                self.io.tool_output("-" * 40)
                # Show header lines
                for line in diff[:2]:
                    self.io.tool_output(line)
                # Show diff with indicators
                for line in diff[2:50]:
                    prefix = "  "
                    if line.startswith('+'):
                        prefix = "+ "
                    elif line.startswith('-'):
                        prefix = "- "
                    elif line.startswith('@@'):
                        prefix = "@@"
                    self.io.tool_output(prefix + line)
                if len(diff) > 50:
                    self.io.tool_output(f"\n... and {len(diff) - 50} more lines")
            else:
                self.io.tool_output(f"Files are identical: {file1} and {file2}")
                
        except Exception as e:
            self.io.tool_error(f"Comparison failed: {e}")

    def cmd_tree(self, args):
        "Show directory tree of files in chat"
        import shlex
        
        # Parse depth limit
        max_depth = 10
        args_parts = shlex.split(args.strip())
        if args_parts and args_parts[0] == "-L":
            try:
                max_depth = int(args_parts[1])
                if max_depth < 1:
                    max_depth = 10
            except (ValueError, IndexError):
                pass
        
        files = sorted(self.coder.get_inchat_relative_files())
        
        if not files:
            self.io.tool_output("No files in chat.")
            return
        
        self.io.tool_output("Files in chat:")
        self.io.tool_output("")
        
        # Build tree structure
        tree = {}
        for f in files:
            parts = f.split('/')
            current = tree
            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]
        
        # Print tree with depth limit
        def print_tree(node, prefix="", depth=0):
            if depth >= max_depth:
                if node:
                    self.io.tool_output(f"{prefix}... ({len(node)} more)")
                return
            
            items = list(node.items())
            for i, (name, children) in enumerate(items):
                is_last = i == len(items) - 1
                # Use ASCII chars for better compatibility
                connector = "+-- " if is_last else "+-- "
                self.io.tool_output(f"{prefix}{connector}{name}")
                if children:
                    extension = "    " if is_last else "|   "
                    print_tree(children, prefix + extension, depth + 1)
        
        print_tree(tree)
        self.io.tool_output("")
        self.io.tool_output(f"Total: {len(files)} files")
        if max_depth < 10:
            self.io.tool_output(f"(Depth limited to {max_depth}, use -L N to change)")

    def cmd_wc(self, args):
        "Count lines, words, and characters in files"
        files = self.coder.get_inchat_relative_files()
        
        if args.strip():
            # Specific file requested
            target = args.strip()
            files = [f for f in files if target in f]
        
        if not files:
            self.io.tool_output("No files in chat to count.")
            return
        
        self.io.tool_output("Word counts:")
        self.io.tool_output("-" * 60)
        self.io.tool_output(f"{'File':<30} {'Lines':>8} {'Words':>8} {'Chars':>10}")
        self.io.tool_output("-" * 60)
        
        total_lines = total_words = total_chars = 0
        binary_skipped = []
        
        for rel_fname in files:
            abs_fname = self.coder.abs_root_path(rel_fname)
            try:
                # Check for binary
                with open(abs_fname, 'rb') as f:
                    chunk = f.read(1024)
                    if b'\x00' in chunk:
                        binary_skipped.append(rel_fname)
                        continue
                
                content = self.io.read_text(abs_fname)
                if content is None:
                    continue
                
                lines = content.count('\n') + 1
                words = len(content.split())
                chars = len(content)
                
                self.io.tool_output(f"{rel_fname:<30} {lines:>8} {words:>8} {chars:>10}")
                
                total_lines += lines
                total_words += words
                total_chars += chars
                
            except Exception as e:
                self.io.tool_output(f"{rel_fname:<30} (error: {e})")
        
        self.io.tool_output("-" * 60)
        self.io.tool_output(f"{'Total':<30} {total_lines:>8} {total_words:>8} {total_chars:>10}")
        
        if binary_skipped:
            self.io.tool_output(f"\n(Skipped {len(binary_skipped)} binary file(s): {', '.join(binary_skipped[:3])})")

    def cmd_head(self, args):
        "Show first N lines of a file"
        import shlex
        
        parts = shlex.split(args.strip())
        if not parts:
            self.show_command_usage("/head", error="Usage: /head [-n N] <file>")
            return
        
        n_lines = 10
        filename = parts[0]
        
        # Parse options
        if parts[0] == "-n" and len(parts) >= 3:
            try:
                n_lines = int(parts[1])
                filename = parts[2]
            except ValueError:
                self.io.tool_error("Invalid line count")
                return
        
        # Find the file
        abs_path = None
        for fname in self.coder.abs_fnames:
            if self.coder.get_rel_fname(fname) == filename or fname.endswith(filename):
                abs_path = fname
                break
        
        if not abs_path:
            abs_path = self.coder.abs_root_path(filename)
            if not Path(abs_path).exists():
                self.io.tool_error(f"File not found: {filename}")
                return
        
        try:
            content = self.io.read_text(abs_path)
            if not content:
                self.io.tool_output("(empty file)")
                return
            
            lines = content.split('\n')
            head_lines = lines[:n_lines]
            
            self.io.tool_output(f"First {len(head_lines)} lines of {filename}:")
            self.io.tool_output("-" * 40)
            for i, line in enumerate(head_lines, 1):
                self.io.tool_output(f"{i:4}: {line}")
                
        except Exception as e:
            self.io.tool_error(f"Error reading file: {e}")

    def cmd_tail(self, args):
        "Show last N lines of a file"
        import shlex
        
        parts = shlex.split(args.strip())
        if not parts:
            self.show_command_usage("/tail", error="Usage: /tail [-n N] <file>")
            return
        
        n_lines = 10
        filename = parts[0]
        
        # Parse options
        if parts[0] == "-n" and len(parts) >= 3:
            try:
                n_lines = int(parts[1])
                filename = parts[2]
            except ValueError:
                self.io.tool_error("Invalid line count")
                return
        
        # Find the file
        abs_path = None
        for fname in self.coder.abs_fnames:
            if self.coder.get_rel_fname(fname) == filename or fname.endswith(filename):
                abs_path = fname
                break
        
        if not abs_path:
            abs_path = self.coder.abs_root_path(filename)
            if not Path(abs_path).exists():
                self.io.tool_error(f"File not found: {filename}")
                return
        
        try:
            content = self.io.read_text(abs_path)
            if not content:
                self.io.tool_output("(empty file)")
                return
            
            lines = content.split('\n')
            tail_lines = lines[-n_lines:] if len(lines) >= n_lines else lines
            
            self.io.tool_output(f"Last {len(tail_lines)} lines of {filename}:")
            self.io.tool_output("-" * 40)
            for i, line in enumerate(tail_lines, max(1, len(lines) - n_lines + 1)):
                self.io.tool_output(f"{i:4}: {line}")
                
        except Exception as e:
            self.io.tool_error(f"Error reading file: {e}")

    def cmd_open(self, args):
        "Open files in default editor"
        import platform
        import subprocess
        import shutil
        
        filename = args.strip()
        if not filename:
            self.show_command_usage("/open", error="Usage: /open <filename>")
            return
        
        # Find the file
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
        
        try:
            system = platform.system()
            if system == "Darwin":  # macOS
                cmd = "open"
                if not shutil.which(cmd):
                    self.io.tool_error(f"'{cmd}' command not found.")
                    return
                result = subprocess.run([cmd, abs_path], capture_output=True, text=True)
            elif system == "Linux":
                cmd = "xdg-open"
                if not shutil.which(cmd):
                    self.io.tool_error(f"'{cmd}' command not found. Try installing xdg-utils.")
                    return
                result = subprocess.run([cmd, abs_path], capture_output=True, text=True)
            elif system == "Windows":
                result = subprocess.run(["start", abs_path], shell=True, capture_output=True, text=True)
            else:
                self.io.tool_error(f"Unsupported platform: {system}")
                return
            
            if result.returncode == 0:
                self.io.tool_output(f"Opened: {filename}")
            else:
                err = result.stderr.strip() if result.stderr else "Unknown error"
                self.io.tool_error(f"Could not open file: {err}")
            
        except Exception as e:
            self.io.tool_error(f"Could not open file: {e}")

    def cmd_pin(self, args):
        "Pin a file to keep it at the top of context"
        filename = args.strip()
        if not filename:
            # List pinned files
            pinned = getattr(self.coder, '_pinned_files', [])
            if pinned:
                self.io.tool_output("Pinned files:")
                for i, fname in enumerate(pinned, 1):
                    rel = self.coder.get_rel_fname(fname) if fname.startswith('/') else fname
                    in_chat = "✓" if fname in self.coder.abs_fnames else "✗"
                    self.io.tool_output(f"  {i}. [{in_chat}] {rel}")
            else:
                self.io.tool_output("No pinned files. Use /pin <file> to pin.")
            return
        
        # Initialize if needed
        if not hasattr(self.coder, '_pinned_files'):
            self.coder._pinned_files = []
        
        # Find file
        abs_path = None
        for fname in self.coder.abs_fnames:
            if self.coder.get_rel_fname(fname) == filename or fname.endswith(filename):
                abs_path = fname
                break
        
        if not abs_path:
            # Try to add it first
            abs_path = self.coder.abs_root_path(filename)
            if not Path(abs_path).exists():
                self.io.tool_error(f"File not found: {filename}")
                return
            self.coder.abs_fnames.add(abs_path)
        
        # Toggle pin
        if abs_path in self.coder._pinned_files:
            self.coder._pinned_files.remove(abs_path)
            self.io.tool_output(f"Unpinned: {filename}")
        else:
            self.coder._pinned_files.append(abs_path)
            self.io.tool_output(f"Pinned: {filename}")

    def cmd_archive(self, args):
        "Archive current session and start fresh"
        from datetime import datetime
        from pathlib import Path
        import json
        
        # Generate archive filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f".aider.archive.{timestamp}.json"
        archive_path = Path(self.coder.root) / archive_name
        
        # Confirm if there are unsaved changes
        has_changes = bool(self.coder.done_messages or self.coder.cur_messages)
        
        if has_changes:
            if not self.io.confirm_ask(
                f"Archive session with {len(self.coder.done_messages) + len(self.coder.cur_messages)} messages and start fresh?",
                default="n"
            ):
                self.io.tool_output("Archive cancelled.")
                return
        
        # Prepare archive data
        archive_data = {
            "version": 1,
            "timestamp": datetime.now().isoformat(),
            "model": self.coder.main_model.name,
            "files": list(self.coder.abs_fnames),
            "read_only_files": list(self.coder.abs_read_only_fnames),
            "messages": self.coder.done_messages + self.coder.cur_messages,
            "total_cost": getattr(self.coder, 'total_cost', 0.0),
            "tokens_sent": getattr(self.coder, 'total_tokens_sent', 0),
            "tokens_received": getattr(self.coder, 'total_tokens_received', 0),
        }
        
        try:
            with open(archive_path, 'w', encoding='utf-8') as f:
                json.dump(archive_data, f, indent=2, default=str)
            
            self.io.tool_output(f"Session archived to: {archive_path}")
            
            # Clear current session
            self._clear_chat_history()
            self.coder.abs_fnames.clear()
            self.coder.abs_read_only_fnames.clear()
            
            # Reset cost tracking
            self.coder.total_cost = 0.0
            self.coder.total_tokens_sent = 0
            self.coder.total_tokens_received = 0
            
            self.io.tool_output("Session cleared. Starting fresh!")
            
        except Exception as e:
            self.io.tool_error(f"Archive failed: {e}")

    def cmd_grep(self, args):
        "Search for pattern across repo (excluding common directories)"
        if not args.strip():
            self.show_command_usage("/grep", error="Usage: /grep <pattern>")
            return
        
        pattern = args.strip()
        
        try:
            import subprocess
            result = subprocess.run(
                [
                    "grep", "-r", "-n", "-I",
                    "--exclude-dir=.git",
                    "--exclude-dir=node_modules",
                    "--exclude-dir=__pycache__",
                    "--exclude-dir=.venv",
                    "--exclude-dir=venv",
                    "--exclude=*.min.js",
                    "--exclude=*.min.css",
                    pattern, self.coder.root
                ],
                capture_output=True,
                text=True,
                encoding=self.io.encoding
            )
            
            if result.returncode in [0, 1]:  # 0 = matches, 1 = no matches
                lines = result.stdout.strip().split('\n') if result.stdout else []
                
                if lines:
                    self.io.tool_output(f"Found {len(lines)} match(es) for '{pattern}':")
                    self.io.tool_output("-" * 40)
                    
                    for line in lines[:20]:
                        # Format: file:line:text
                        if ':' in line:
                            parts = line.split(':', 2)
                            if len(parts) >= 3:
                                fname, lineno, text = parts
                                rel_fname = fname.replace(self.coder.root + '/', '')
                                self.io.tool_output(f"{rel_fname}:{lineno}: {text[:60]}")
                    
                    if len(lines) > 20:
                        self.io.tool_output(f"\n... and {len(lines) - 20} more matches")
                else:
                    self.io.tool_output(f"No matches found for '{pattern}'.")
            else:
                self.io.tool_error(f"grep error: {result.stderr}")
                
        except FileNotFoundError:
            self.io.tool_error("grep command not found. This command requires grep (Unix/Linux/Mac).")
        except Exception as e:
            self.io.tool_error(f"Error: {e}")

    def cmd_untracked(self, args):
        "Show untracked files in git repo"
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return
        
        try:
            import subprocess
            result = subprocess.run(
                ["git", "-C", self.coder.root, "ls-files", "--others", "--exclude-standard"],
                capture_output=True,
                text=True,
                encoding=self.io.encoding
            )
            
            if result.returncode != 0:
                self.io.tool_error("Could not get untracked files.")
                return
            
            files = [f for f in result.stdout.strip().split('\n') if f]
            
            if not files:
                self.io.tool_output("No untracked files.")
                return
            
            self.io.tool_output(f"Untracked files ({len(files)}):")
            self.io.tool_output("-" * 40)
            
            for fname in files[:30]:
                self.io.tool_output(f"  {fname}")
            
            if len(files) > 30:
                self.io.tool_output(f"  ... and {len(files) - 30} more")
            
            self.io.tool_output("\nUse 'git add <file>' to track, or add to .gitignore to ignore.")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")

    def cmd_recent(self, args):
        "Show recently modified files"
        if not self.coder.repo:
            self.io.tool_error("No git repository found.")
            return
        
        try:
            # Get recently modified files from git
            import subprocess
            result = subprocess.run(
                ["git", "-C", self.coder.root, "diff", "--name-only", "HEAD~5..HEAD"],
                capture_output=True,
                text=True,
                encoding=self.io.encoding
            )
            
            if result.returncode != 0:
                self.io.tool_error("Could not get recent files.")
                return
            
            files = [f for f in result.stdout.strip().split('\n') if f]
            
            if not files:
                self.io.tool_output("No recent changes in last 5 commits.")
                return
            
            self.io.tool_output(f"Recently modified files ({len(files)}):")
            self.io.tool_output("-" * 40)
            
            for fname in files[:20]:
                in_chat = "✓" if fname in self.coder.get_inchat_relative_files() else " "
                self.io.tool_output(f"  [{in_chat}] {fname}")
            
            if len(files) > 20:
                self.io.tool_output(f"  ... and {len(files) - 20} more")
            
            self.io.tool_output("\nUse /add <file> to add files to chat.")
            
        except Exception as e:
            self.io.tool_error(f"Error: {e}")

    def cmd_map(self, args):
        "Show repository map status and statistics"
        if not self.coder.repo_map:
            self.io.tool_output("Repository map is disabled.")
            self.io.tool_output("Enable with --map-tokens or check your config.")
            return
        
        self.io.tool_output("Repository Map Status:")
        self.io.tool_output("-" * 40)
        
        # Basic settings
        max_tokens = self.coder.repo_map.max_map_tokens
        refresh = self.coder.repo_map.refresh
        self.io.tool_output(f"Max tokens: {max_tokens}")
        self.io.tool_output(f"Refresh mode: {refresh}")
        
        # File counts
        if self.coder.repo:
            all_files = len(self.coder.repo.get_tracked_files())
            self.io.tool_output(f"\nTotal tracked files: {all_files}")
        
        # Files in chat
        chat_files = len(self.coder.get_inchat_relative_files())
        self.io.tool_output(f"Files in chat: {chat_files}")
        
        # Show sample of repo map if available
        other_files = set(self.coder.get_all_abs_files()) - self.coder.abs_fnames
        if self.coder.repo_map and chat_files > 0:
            repo_content = self.coder.repo_map.get_repo_map(self.coder.abs_fnames, other_files)
            if repo_content:
                tokens = self.coder.main_model.token_count(repo_content)
                self.io.tool_output(f"\nCurrent map size: ~{tokens} tokens")
                
                # Show first few lines
                lines = repo_content.split('\n')[:10]
                self.io.tool_output("\nMap preview (first 10 lines):")
                for line in lines:
                    self.io.tool_output(f"  {line[:60]}")
                if len(repo_content.split('\n')) > 10:
                    self.io.tool_output("  ...")

    def cmd_size(self, args):
        "Show sizes of files in chat"
        from pathlib import Path
        
        files = self.coder.get_inchat_relative_files()
        if not files:
            self.io.tool_output("No files in chat.")
            return
        
        self.io.tool_output("File sizes:")
        self.io.tool_output("-" * 40)
        
        total_size = 0
        total_lines = 0
        
        for rel_fname in sorted(files):
            abs_fname = self.coder.abs_root_path(rel_fname)
            try:
                path = Path(abs_fname)
                size = path.stat().st_size
                total_size += size
                
                # Count lines
                content = self.io.read_text(abs_fname)
                lines = content.count('\n') + 1 if content else 0
                total_lines += lines
                
                # Format size
                if size < 1024:
                    size_str = f"{size}B"
                elif size < 1024 * 1024:
                    size_str = f"{size / 1024:.1f}KB"
                else:
                    size_str = f"{size / (1024 * 1024):.1f}MB"
                
                self.io.tool_output(f"{rel_fname:<30} {size_str:>8} {lines:>6} lines")
            except Exception as e:
                self.io.tool_output(f"{rel_fname:<30} (error: {e})")
        
        self.io.tool_output("-" * 40)
        if total_size < 1024:
            total_str = f"{total_size}B"
        elif total_size < 1024 * 1024:
            total_str = f"{total_size / 1024:.1f}KB"
        else:
            total_str = f"{total_size / (1024 * 1024):.1f}MB"
        
        self.io.tool_output(f"{'Total':<30} {total_str:>8} {total_lines:>6} lines")

    def cmd_exclude(self, args):
        "Add pattern to .aiderignore to exclude files from repo-map"
        from pathlib import Path
        
        pattern = args.strip()
        if not pattern:
            self.show_command_usage("/exclude", error="Please provide a pattern to exclude.")
            return
        
        # Find or create .aiderignore
        aiderignore_path = Path(self.coder.root) / ".aiderignore"
        
        # Read existing content
        existing = []
        if aiderignore_path.exists():
            try:
                existing = aiderignore_path.read_text().split('\n')
            except Exception as e:
                self.io.tool_error(f"Could not read .aiderignore: {e}")
                return
        
        # Check if pattern already exists
        if pattern in existing:
            self.io.tool_output(f"Pattern '{pattern}' already in .aiderignore")
            return
        
        # Add pattern
        try:
            with open(aiderignore_path, 'a', encoding='utf-8') as f:
                if existing and existing[-1] != '':
                    f.write('\n')
                f.write(f"{pattern}\n")
            
            self.io.tool_output(f"Added '{pattern}' to .aiderignore")
            
            # Also drop the file if it's currently in chat
            for fname in list(self.coder.abs_fnames):
                rel = self.coder.get_rel_fname(fname)
                if pattern in rel or rel.endswith(pattern.replace('*', '')):
                    self.coder.abs_fnames.discard(fname)
                    self.io.tool_output(f"Dropped {rel} from chat (matches exclusion)")
            
        except Exception as e:
            self.io.tool_error(f"Could not update .aiderignore: {e}")

    def cmd_find(self, args):
        "Search for text within files in the chat"
        import re
        
        query = args.strip()
        if not query:
            self.show_command_usage("/find", error="Please provide a search term.")
            return
        
        files = self.coder.get_inchat_relative_files()
        if not files:
            self.io.tool_error("No files in chat to search.")
            return
        
        # Compile regex for case-insensitive search
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as e:
            self.io.tool_error(f"Invalid regex pattern: {e}")
            return
        
        matches = []
        for rel_fname in files:
            abs_fname = self.coder.abs_root_path(rel_fname)
            try:
                content = self.io.read_text(abs_fname)
                if not content:
                    continue
                
                for i, line in enumerate(content.split('\n'), 1):
                    if pattern.search(line):
                        matches.append((rel_fname, i, line.strip()))
            except Exception as e:
                self.io.tool_warning(f"Could not search {rel_fname}: {e}")
        
        if matches:
            self.io.tool_output(f"Found {len(matches)} match(es) for '{query}':")
            self.io.tool_output("-" * 40)
            
            # Group by file
            current_file = None
            for fname, line_num, line_text in matches:
                if fname != current_file:
                    current_file = fname
                    self.io.tool_output(f"\n{fname}:")
                self.io.tool_output(f"  {line_num}: {line_text[:80]}")
        else:
            self.io.tool_output(f"No matches found for '{query}'.")

    def cmd_reload(self, args):
        "Reload files from disk, discarding any unsaved changes"
        args_clean = args.strip().lower()
        force = args_clean in ("--force", "-f")
        dry_run = "--dry-run" in args_clean
        
        files = list(self.coder.abs_fnames)
        if not files:
            self.io.tool_output("No files in chat to reload.")
            return
        
        # Check for dirty files
        dirty_in_chat = []
        if self.coder.repo:
            dirty_files = set(self.coder.repo.get_dirty_files())
            dirty_in_chat = [f for f in files if f in dirty_files]
        
        if dry_run:
            self.io.tool_output("Dry run - files that would be reloaded:")
            for fname in files:
                rel = self.coder.get_rel_fname(fname)
                status = " (modified)" if fname in dirty_in_chat else ""
                self.io.tool_output(f"  {rel}{status}")
            return
        
        if not force and dirty_in_chat:
            file_list = ", ".join(self.coder.get_rel_fname(f) for f in dirty_in_chat[:3])
            if len(dirty_in_chat) > 3:
                file_list += f" and {len(dirty_in_chat) - 3} more"
            
            if not self.io.confirm_ask(
                f"Reload {len(dirty_in_chat)} modified file(s)? Unsaved changes will be lost.",
                default="n",
            ):
                self.io.tool_output("Reload cancelled.")
                return
        
        reloaded = 0
        errors = []
        
        for fname in files:
            try:
                # Re-read file content
                content = self.io.read_text(fname)
                if content is not None:
                    reloaded += 1
                else:
                    errors.append(f"Could not read {self.coder.get_rel_fname(fname)}")
            except Exception as e:
                errors.append(f"{self.coder.get_rel_fname(fname)}: {e}")
        
        self.io.tool_output(f"Reloaded {reloaded} file(s) from disk.")
        if errors:
            self.io.tool_warning("Errors:")
            for err in errors:
                self.io.tool_output(f"  {err}")

    def cmd_context(self, args):
        "Show current context: files in chat, model, and mode"
        self.io.tool_output("Current Context:")
        self.io.tool_output("-" * 40)
        
        # Model info
        self.io.tool_output(f"Model: {self.coder.main_model.name}")
        self.io.tool_output(f"Mode: {self.coder.edit_format}")
        
        # Git info
        if self.coder.repo:
            rel_repo_dir = self.coder.repo.get_rel_repo_dir()
            dirty_files = len(self.coder.repo.get_dirty_files())
            self.io.tool_output(f"Repo: {rel_repo_dir} ({dirty_files} files modified)")
        
        # Files in chat
        files = sorted(self.coder.get_inchat_relative_files())
        pinned = getattr(self.coder, '_pinned_files', [])
        if files:
            self.io.tool_output(f"\nFiles in chat ({len(files)}):")
            for fname in files:
                is_pinned = "📌 " if fname in pinned else "   "
                self.io.tool_output(f"{is_pinned}✓ {fname}")
        else:
            self.io.tool_output("\nNo files in chat. Use /add <file> to add files.")
        
        # Show pinned indicator
        if pinned:
            self.io.tool_output(f"\n(📌 = pinned file, kept at top of context)")
        
        # Read-only files
        ro_files = sorted(self.coder.abs_read_only_fnames)
        if ro_files:
            self.io.tool_output(f"\nRead-only files ({len(ro_files)}):")
            for fname in ro_files:
                rel_fname = self.coder.get_rel_fname(fname)
                self.io.tool_output(f"  ○ {rel_fname}")
        
        # Recent messages summary
        messages = self.coder.done_messages + self.coder.cur_messages
        user_msgs = sum(1 for m in messages if m.get("role") == "user")
        assistant_msgs = sum(1 for m in messages if m.get("role") == "assistant")
        self.io.tool_output(f"\nChat: {user_msgs} user, {assistant_msgs} assistant messages")

    def cmd_export(self, args):
        "Export the conversation to a markdown file"
        from datetime import datetime
        from pathlib import Path
        
        filename = args.strip()
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"aider-chat-{timestamp}.md"
        
        # Resolve path securely
        filepath = self._resolve_session_path(filename)
        if filepath is None:
            return
        
        messages = self.coder.done_messages + self.coder.cur_messages
        if not messages:
            self.io.tool_output("No chat history to export.")
            return
        
        try:
            lines = [f"# Aider Conversation Export\n"]
            lines.append(f"Date: {datetime.now().isoformat()}\n")
            lines.append(f"Model: {self.coder.main_model.name}\n")
            lines.append(f"Files: {', '.join(self.coder.get_inchat_relative_files()) or 'None'}\n")
            lines.append("\n---\n\n")
            
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls")
                
                # Handle content that might be a list (some message formats)
                if isinstance(content, list):
                    content = "\n".join(str(c) for c in content)
                
                if role == "user":
                    lines.append(f"## User\n\n{content}\n\n")
                elif role == "assistant":
                    lines.append(f"## Assistant\n\n")
                    if content:
                        lines.append(f"{content}\n\n")
                    if tool_calls:
                        lines.append("*Tool calls:*\n")
                        for tc in tool_calls:
                            fn = tc.get("function", {})
                            fn_name = fn.get("name", "unknown")
                            lines.append(f"- `{fn_name}(...)`\n")
                        lines.append("\n")
                elif role == "system":
                    # Skip system messages or show brief indicator
                    pass
            
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
            self.io.tool_output(f"Conversation exported to: {filepath}")
            
        except Exception as e:
            self.io.tool_error(f"Failed to export: {e}")

    def cmd_reset(self, args):
        "Drop all files and clear the chat history"
        # Check for --force or -f flag to skip confirmation
        args_clean = args.strip().lower()
        if args_clean not in ("--force", "-f"):
            if not self.io.confirm_ask(
                "Drop all files and clear chat history?",
                default="n",
            ):
                self.io.tool_output("Reset cancelled.")
                return
        self._drop_all_files()
        self._clear_chat_history()
        self.io.tool_output("All files dropped and chat history cleared.")

    def _resolve_session_path(self, filename):
        """Resolve and validate a session file path.
        
        Returns resolved path or None if invalid (path traversal attempt).
        """
        from pathlib import Path
        
        filepath = Path(filename)
        if not filepath.is_absolute():
            filepath = Path(self.coder.root) / filepath
        
        # Resolve to absolute path
        filepath = filepath.resolve()
        root = Path(self.coder.root).resolve()
        
        # Security: Prevent path traversal outside repo root
        try:
            filepath.relative_to(root)
        except ValueError:
            self.io.tool_error(f"Invalid path: must be within repo root ({root})")
            return None
        
        return filepath

    def cmd_save(self, args):
        "Save the current conversation to a file for later restoration"
        import json
        from datetime import datetime
        from pathlib import Path
        
        # Default filename or use provided
        filename = args.strip()
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f".aider.session.{timestamp}.json"
        
        # Security: Validate path
        filepath = self._resolve_session_path(filename)
        if filepath is None:
            return
        
        # Prepare session data with ISO timestamp
        session_data = {
            "version": 1,
            "model": self.coder.main_model.name,
            "files": list(self.coder.abs_fnames),
            "read_only_files": list(self.coder.abs_read_only_fnames),
            "messages": self.coder.done_messages + self.coder.cur_messages,
            "timestamp": datetime.now().isoformat(),
        }
        
        try:
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(session_data, f, indent=2, default=str)
            self.io.tool_output(f"Session saved to: {filepath}")
            self.io.tool_output(f"  Files: {len(session_data['files'])}")
            self.io.tool_output(f"  Messages: {len(session_data['messages'])}")
        except Exception as e:
            self.io.tool_error(f"Failed to save session: {e}")

    def cmd_load(self, args):
        "Load a previously saved conversation"
        import json
        from pathlib import Path
        
        filename = args.strip()
        if not filename:
            self.show_command_usage("/load", error="Please provide a session file to load.")
            return
        
        # Security: Validate path
        filepath = self._resolve_session_path(filename)
        if filepath is None:
            return
        
        if not filepath.exists():
            self.io.tool_error(f"Session file not found: {filepath}")
            return
        
        # Security: Check file size (prevent loading huge files)
        max_size = 50 * 1024 * 1024  # 50MB limit
        if filepath.stat().st_size > max_size:
            self.io.tool_error(f"Session file too large (>50MB): {filepath}")
            return
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                session_data = json.load(f)
            
            # Validate required fields
            if not isinstance(session_data, dict):
                raise ValueError("Invalid session format: expected object")
            if session_data.get("version") != 1:
                version = session_data.get("version", "unknown")
                self.io.tool_warning(f"Session version {version} may not be fully compatible")
            if "messages" not in session_data:
                raise ValueError("Invalid session: missing 'messages' field")
            
            # Confirm before overwriting current session
            if self.coder.done_messages or self.coder.cur_messages:
                if not self.io.confirm_ask(
                    f"Load session from {filepath.name}? This will replace current conversation.",
                    default="n",
                ):
                    self.io.tool_output("Load cancelled.")
                    return
            
            # Restore files (only if they still exist)
            restored_files = 0
            for fname in session_data.get("files", []):
                if Path(fname).exists():
                    self.coder.abs_fnames.add(fname)
                    restored_files += 1
            
            restored_readonly = 0
            for fname in session_data.get("read_only_files", []):
                if Path(fname).exists():
                    self.coder.abs_read_only_fnames.add(fname)
                    restored_readonly += 1
            
            # Restore messages (deep copy to avoid reference issues)
            import copy
            self.coder.done_messages = copy.deepcopy(session_data.get("messages", []))
            self.coder.cur_messages = []
            
            self.io.tool_output(f"Session loaded from: {filepath}")
            self.io.tool_output(f"  Files restored: {restored_files} (of {len(session_data.get('files', []))})")
            self.io.tool_output(f"  Messages: {len(self.coder.done_messages)}")
            
        except json.JSONDecodeError as e:
            self.io.tool_error(f"Invalid session file format: {e}")
        except ValueError as e:
            self.io.tool_error(str(e))
        except Exception as e:
            self.io.tool_error(f"Failed to load session: {e}")

    def cmd_add(self, args):
        "Add files to the chat so aider can edit them or review them in detail"
        from aider.utils import validate_multimodal_file

        all_matched_files = set()

        if not args.strip():
            self.show_command_usage("/add", error="Please provide one or more files to add.")
            return

        filenames = self.parse_filename_args(args, command_name="/add")
        if filenames is None:
            return
        for word in filenames:
            if Path(word).is_absolute():
                fname = Path(word)
            else:
                fname = Path(self.coder.root) / word

            if self.coder.repo and self.coder.repo.ignored_file(fname):
                self.io.tool_warning(f"Skipping {fname} due to aiderignore or --subtree-only.")
                continue

            if fname.exists():
                if fname.is_file():
                    all_matched_files.add(str(fname))
                    continue
                word = re.sub(r"([\*\?\[\]])", r"[\1]", word)

            matched_files = self.glob_filtered_to_repo(word)
            if matched_files:
                all_matched_files.update(matched_files)
                continue

            if "*" in str(fname) or "?" in str(fname):
                self.io.tool_error(
                    f"No match, and cannot create file with wildcard characters: {fname}"
                )
                continue

            if fname.exists() and fname.is_dir() and self.coder.repo:
                self.io.tool_error(f"Directory {fname} is not in git.")
                self.io.tool_output(f"You can add to git with: /git add {fname}")
                continue

            if self.io.confirm_ask(f"No files matched '{word}'. Do you want to create {fname}?"):
                try:
                    fname.parent.mkdir(parents=True, exist_ok=True)
                    fname.touch()
                    all_matched_files.add(str(fname))
                except OSError as e:
                    self.io.tool_error(f"Error creating file {fname}: {e}")

        for matched_file in sorted(all_matched_files):
            abs_file_path = self.coder.abs_root_path(matched_file)

            if (
                not abs_file_path.startswith(self.coder.root)
                and not is_image_file(matched_file)
                and self.coder.auto_commits
            ):
                self.io.tool_error(
                    f"Can not add {abs_file_path}, which is not within {self.coder.root}"
                )
                continue

            if (
                self.coder.repo
                and self.coder.repo.git_ignored_file(matched_file)
                and not self.coder.add_gitignore_files
            ):
                self.io.tool_error(f"Can't add {matched_file} which is in gitignore")
                continue

            if abs_file_path in self.coder.abs_fnames:
                self.io.tool_error(f"{matched_file} is already in the chat as an editable file")
                continue
            elif abs_file_path in self.coder.abs_read_only_fnames:
                if self.coder.repo:
                    can_edit = self.coder.repo.path_in_repo(matched_file)
                else:
                    can_edit = abs_file_path.startswith(self.coder.root)

                if can_edit:
                    self.coder.abs_read_only_fnames.remove(abs_file_path)
                    self.coder.abs_fnames.add(abs_file_path)
                    self.io.tool_output(
                        f"Moved {matched_file} from read-only to editable files in the chat"
                    )
                else:
                    self.io.tool_error(
                        f"Cannot add {matched_file} as it's not part of the repository"
                    )
            else:
                is_valid, error = validate_multimodal_file(matched_file, self.coder.main_model)
                if not is_valid:
                    self.io.tool_error(error)
                    continue

                content = self.io.read_text(abs_file_path)
                if content is None:
                    self.io.tool_error(f"Unable to read {matched_file}")
                else:
                    self.coder.abs_fnames.add(abs_file_path)
                    fname = self.coder.get_rel_fname(abs_file_path)
                    self.io.tool_output(f"Added {fname} to the chat")
                    self.coder.check_added_files()

    def completions_drop(self):
        files = self.coder.get_inchat_relative_files()
        read_only_files = [self.coder.get_rel_fname(fn) for fn in self.coder.abs_read_only_fnames]
        all_files = files + read_only_files
        all_files = [self.quote_fname(fn) for fn in all_files]
        return all_files

    def cmd_drop(self, args=""):
        "Remove files from the chat session to free up context space"

        if not args.strip():
            if self.original_read_only_fnames:
                self.io.tool_output(
                    "Dropping all files from the chat session except originally read-only files."
                )
            else:
                self.io.tool_output("Dropping all files from the chat session.")
            self._drop_all_files()
            return

        filenames = self.parse_filename_args(args, command_name="/drop")
        if filenames is None:
            return
        for word in filenames:
            expanded_word = os.path.expanduser(word)

            read_only_matched = []
            for f in self.coder.abs_read_only_fnames:
                if expanded_word in f:
                    read_only_matched.append(f)
                    continue
                try:
                    abs_word = os.path.abspath(expanded_word)
                    if os.path.samefile(abs_word, f):
                        read_only_matched.append(f)
                except (FileNotFoundError, OSError):
                    continue

            for matched_file in read_only_matched:
                self.coder.abs_read_only_fnames.remove(matched_file)
                self.io.tool_output(f"Removed read-only file {matched_file} from the chat")

            if any(c in expanded_word for c in "*?[]"):
                matched_files = self.glob_filtered_to_repo(expanded_word)
            else:
                matched_files = [
                    self.coder.get_rel_fname(f) for f in self.coder.abs_fnames if expanded_word in f
                ]

            if not matched_files:
                matched_files.append(expanded_word)

            for matched_file in matched_files:
                abs_fname = self.coder.abs_root_path(matched_file)
                if abs_fname in self.coder.abs_fnames:
                    self.coder.abs_fnames.remove(abs_fname)
                    self.io.tool_output(f"Removed {matched_file} from the chat")

    def cmd_exit(self, args):
        "Exit the application"
        import sys

        self.coder.event("exit", reason="/exit")
        sys.exit()

    def cmd_quit(self, args):
        "Exit the application"
        self.cmd_exit(args)

    def cmd_ls(self, args):
        "List all known files and indicate which are included in the chat session"

        files = self.coder.get_all_relative_files()

        other_files = []
        chat_files = []
        read_only_files = []
        for file in files:
            abs_file_path = self.coder.abs_root_path(file)
            if abs_file_path in self.coder.abs_fnames:
                chat_files.append(file)
            else:
                other_files.append(file)

        for abs_file_path in self.coder.abs_read_only_fnames:
            rel_file_path = self.coder.get_rel_fname(abs_file_path)
            read_only_files.append(rel_file_path)

        if not chat_files and not other_files and not read_only_files:
            self.io.tool_output("\nNo files in chat, git repo, or read-only list.")
            return

        if other_files:
            self.io.tool_output("Repo files not in the chat:\n")
        for file in other_files:
            self.io.tool_output(f"  {file}")

        if read_only_files:
            self.io.tool_output("\nRead-only files:\n")
        for file in read_only_files:
            self.io.tool_output(f"  {file}")

        if chat_files:
            self.io.tool_output("\nFiles in chat:\n")
        for file in chat_files:
            self.io.tool_output(f"  {file}")

    def cmd_load(self, args):
        "Load and execute commands from a file"
        if not args.strip():
            self.io.tool_error("Please provide a filename containing commands to load.")
            return

        # Security: Validate path
        filepath = self._resolve_session_path(args.strip())
        if filepath is None:
            return

        try:
            with open(filepath, "r", encoding=self.io.encoding, errors="replace") as f:
                commands = f.readlines()
        except FileNotFoundError:
            self.io.tool_error(f"File not found: {filepath}")
            return
        except Exception as e:
            self.io.tool_error(f"Error reading file: {e}")
            return

        from aider.commands import SwitchCoder

        for cmd in commands:
            cmd = cmd.strip()
            if not cmd or cmd.startswith("#"):
                continue

            self.io.tool_output(f"\nExecuting: {cmd}")
            try:
                self.run(cmd)
            except SwitchCoder:
                self.io.tool_error(
                    f"Command '{cmd}' is only supported in interactive mode, skipping."
                )

    def completions_raw_load(self, document, complete_event):
        return self.completions_raw_read_only(document, complete_event)

    def cmd_save(self, args):
        "Save commands to a file that can reconstruct the current chat session's files"
        if not args.strip():
            self.io.tool_error("Please provide a filename to save the commands to.")
            return

        # Security: Validate path
        filepath = self._resolve_session_path(args.strip())
        if filepath is None:
            return

        try:
            with open(filepath, "w", encoding=self.io.encoding) as f:
                f.write("/drop\n")
                for fname in sorted(self.coder.abs_fnames):
                    rel_fname = self.coder.get_rel_fname(fname)
                    f.write(f"/add       {rel_fname}\n")

                for fname in sorted(self.coder.abs_read_only_fnames):
                    if Path(fname).is_relative_to(self.coder.root):
                        rel_fname = self.coder.get_rel_fname(fname)
                        f.write(f"/read-only {rel_fname}\n")
                    else:
                        f.write(f"/read-only {fname}\n")

            self.io.tool_output(f"Saved commands to {filepath}")
        except Exception as e:
            self.io.tool_error(f"Error saving commands to file: {e}")

    def completions_raw_save(self, document, complete_event):
        return self.completions_raw_read_only(document, complete_event)

    def cmd_read_only(self, args):
        "Add files to the chat that are for reference only, or turn added files to read-only"
        if not args.strip():
            for fname in list(self.coder.abs_fnames):
                self.coder.abs_fnames.remove(fname)
                self.coder.abs_read_only_fnames.add(fname)
                rel_fname = self.coder.get_rel_fname(fname)
                self.io.tool_output(f"Converted {rel_fname} to read-only")
            return

        filenames = self.parse_filename_args(args, command_name="/read-only")
        if filenames is None:
            return
        all_paths = []

        for pattern in filenames:
            expanded_pattern = expanduser(pattern)
            path_obj = Path(expanded_pattern)
            is_abs = path_obj.is_absolute()
            if not is_abs:
                path_obj = Path(self.coder.root) / path_obj

            matches = []
            if path_obj.exists():
                matches = [path_obj]
            else:
                if is_abs:
                    matches = [Path(p) for p in glob.glob(expanded_pattern)]
                else:
                    matches = list(Path(self.coder.root).glob(expanded_pattern))

            if not matches:
                self.io.tool_error(f"No matches found for: {pattern}")
            else:
                all_paths.extend(matches)

        for path in sorted(all_paths):
            abs_path = self.coder.abs_root_path(path)
            if os.path.isfile(abs_path):
                self._add_read_only_file(abs_path, path)
            elif os.path.isdir(abs_path):
                self._add_read_only_directory(abs_path, path)
            else:
                self.io.tool_error(f"Not a file or directory: {abs_path}")

    def _add_read_only_file(self, abs_path, original_name):
        from aider.utils import validate_multimodal_file

        is_valid, error = validate_multimodal_file(original_name, self.coder.main_model)
        if not is_valid:
            self.io.tool_error(error)
            return

        if abs_path in self.coder.abs_read_only_fnames:
            self.io.tool_error(f"{original_name} is already in the chat as a read-only file")
            return
        elif abs_path in self.coder.abs_fnames:
            self.coder.abs_fnames.remove(abs_path)
            self.coder.abs_read_only_fnames.add(abs_path)
            self.io.tool_output(
                f"Moved {original_name} from editable to read-only files in the chat"
            )
        else:
            self.coder.abs_read_only_fnames.add(abs_path)
            self.io.tool_output(f"Added {original_name} to read-only files.")

    def _add_read_only_directory(self, abs_path, original_name):
        added_files = 0
        for root, _, files in os.walk(abs_path):
            for file in files:
                file_path = os.path.join(root, file)
                if (
                    file_path not in self.coder.abs_fnames
                    and file_path not in self.coder.abs_read_only_fnames
                ):
                    self.coder.abs_read_only_fnames.add(file_path)
                    added_files += 1

        if added_files > 0:
            self.io.tool_output(
                f"Added {added_files} files from directory {original_name} to read-only files."
            )
        else:
            self.io.tool_output(f"No new files added from directory {original_name}.")

    def cmd_map(self, args):
        "Print out the current repository map"
        repo_map = self.coder.get_repo_map()
        if repo_map:
            self.io.tool_output(repo_map)
        else:
            self.io.tool_output("No repository map available.")

    def cmd_map_refresh(self, args):
        "Force a refresh of the repository map"
        repo_map = self.coder.get_repo_map(force_refresh=True)
        if repo_map:
            self.io.tool_output("The repo map has been refreshed, use /map to view it.")
