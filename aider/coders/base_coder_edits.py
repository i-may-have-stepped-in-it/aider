import json
import traceback
from json.decoder import JSONDecodeError

from aider import urls
from aider.repo import ANY_GIT_ERROR


class BaseCoderEditsMixin:
    """Edit preparation, update application, and partial argument parsing."""

    def prepare_to_edit(self, edits):
        res = []
        seen = dict()

        self.need_commit_before_edits = set()

        for edit in edits:
            path = edit[0]
            if path is None:
                res.append(edit)
                continue
            if path == "python":
                from ..dump import dump

                dump(edits)
            if path in seen:
                allowed = seen[path]
            else:
                allowed = self.allowed_to_edit(path)
                seen[path] = allowed

            if allowed:
                res.append(edit)

        self.dirty_commit()
        self.need_commit_before_edits = set()

        return res

    def apply_updates(self):
        edited = set()
        try:
            edits = self.get_edits()
            edits = self.apply_edits_dry_run(edits)

            if getattr(self, "review_mode", False):
                edits = self.review_edits(edits)
                if not edits:
                    self.io.tool_output("No changes were approved.")
                    return set()

            hooks = self._get_hooks_manager()
            if hooks:
                try:
                    pre_result = hooks.execute("pre_edit", edits=edits, coder=self)
                    if pre_result.get("data", {}).get("edits") is not None:
                        edits = pre_result["data"]["edits"]
                except Exception as e:
                    if hooks.verbose:
                        self.io.tool_error(f"Hook error (pre_edit): {e}")

            edits = self.prepare_to_edit(edits)
            edited = set(edit[0] for edit in edits)

            self.apply_edits(edits)
        except ValueError as err:
            self.num_malformed_responses += 1

            err = err.args[0]

            self.io.tool_error("The LLM did not conform to the edit format.")
            self.io.tool_output(urls.edit_errors)
            self.io.tool_output()
            self.io.tool_output(str(err))

            self.reflected_message = (
                f"The LLM did not conform to the edit format: {str(err)}\n"
                "To fix this, please provide the complete updated content for each file "
                "that needs changes, using the required format exactly as specified. "
                "DO NOT provide examples of the format or conversational confirmation. "
                "JUST provide the actual file listings for the changes I requested."
            )
            return edited

        except ANY_GIT_ERROR as err:
            self.io.tool_error(str(err))
            return edited
        except Exception as err:
            self.io.tool_error("Exception while updating files:")
            self.io.tool_error(str(err), strip=False)

            traceback.print_exc()

            self.reflected_message = str(err)
            return edited

        for path in edited:
            if self.dry_run:
                self.io.tool_output(f"Did not apply edit to {path} (--dry-run)")
            else:
                self.io.tool_output(f"Applied edit to {path}")

        if hooks:
            try:
                hooks.execute("post_edit", edited_files=edited, coder=self)
            except Exception as e:
                if hooks.verbose:
                    self.io.tool_error(f"Hook error (post_edit): {e}")

        return edited

    def review_edits(self, edits):
        """Review each edit with the user."""
        approved_edits = []

        for edit in edits:
            # Different formats have different edit structures
            if len(edit) == 2:  # WholeFile format (path, new_content)
                path, new_content = edit
                original = None
                updated = None
            elif len(edit) == 3:  # EditBlock format (path, original, updated)
                path, original, updated = edit
                new_content = None
            else:
                approved_edits.append(edit)
                continue

            full_path = self.abs_root_path(path)
            old_content = self.io.read_text(full_path) if self.io.path_exists(full_path) else ""

            # For edit blocks, calculate the new content to show in diff
            if original is not None and updated is not None:
                from .editblock_coder import do_replace
                new_content = do_replace(full_path, old_content, original, updated, getattr(self, "fence", "```"))
                if not new_content:
                    # If it failed to match, we still show the failed block
                    new_content = f"### [SEARCH/REPLACE FAILED]\n{updated}"

            choice = self.io.review_diff(path, old_content, new_content or "")

            if choice == "accept":
                approved_edits.append(edit)
            elif choice == "quit":
                break
            elif choice == "edit":
                # User wants to manually edit - for now just accept it and let them fix later
                # Or we could launch an editor here. Let's keep it simple for MVP.
                approved_edits.append(edit)
            # "reject" simply skips adding it to approved_edits

        return approved_edits

    def parse_partial_args(self):
        data = self.partial_response_function_call.get("arguments")
        if not data:
            return

        try:
            return json.loads(data)
        except JSONDecodeError:
            pass

        try:
            return json.loads(data + "]}")
        except JSONDecodeError:
            pass

        try:
            return json.loads(data + "}]}")
        except JSONDecodeError:
            pass

        try:
            return json.loads(data + '"}]}')
        except JSONDecodeError:
            pass
