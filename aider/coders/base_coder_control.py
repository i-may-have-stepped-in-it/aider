import asyncio
import re
import sys
import threading
import time
from typing import List, Optional

from rich.console import Console

from aider.io import ConfirmGroup


class BaseCoderControlMixin:
    def run_stream(self, user_message):
        self.io.user_input(user_message)
        self.init_before_message()

        hooks = self._get_hooks_manager()
        if hooks:
            try:
                pre_result = hooks.execute("pre_send", message=user_message, coder=self)
                if pre_result.get("data", {}).get("message") is not None:
                    user_message = pre_result["data"]["message"]
            except Exception as e:
                if hooks.verbose:
                    self.io.tool_error(f"Hook error (pre_send): {e}")

        yield from self.send_message(user_message)

        if hooks:
            try:
                hooks.execute(
                    "post_send",
                    message=user_message,
                    response=self.partial_response_content,
                    coder=self,
                )
            except Exception as e:
                if hooks.verbose:
                    self.io.tool_error(f"Hook error (post_send): {e}")

    def run(self, with_message=None, preproc=True):
        """Synchronous run method."""
        try:
            if with_message:
                self.io.user_input(with_message)
                self.run_one(with_message, preproc)
                return self.partial_response_content
            while True:
                try:
                    if not self.io.placeholder:
                        self.copy_context()
                    user_message = self.get_input()
                    self.run_one(user_message, preproc)
                    self.show_undo_hint()
                except KeyboardInterrupt:
                    self.keyboard_interrupt()
        except EOFError:
            return

    def get_input(self):
        inchat_files = self.get_inchat_relative_files()
        read_only_files = [self.get_rel_fname(fname) for fname in self.abs_read_only_fnames]
        all_files = sorted(set(inchat_files + read_only_files))
        edit_format = "" if self.edit_format == self.main_model.edit_format else self.edit_format
        return self.io.get_input(
            self.root,
            all_files,
            self.get_addable_relative_files(),
            self.commands,
            self.abs_read_only_fnames,
            edit_format=edit_format,
        )

    def preproc_user_input(self, inp):
        if not inp:
            return

        if self.commands.is_command(inp):
            return self.commands.run(inp)

        self.check_for_file_mentions(inp)
        inp = self.check_for_urls(inp)

        return inp

    def run_one(self, user_message, preproc):
        self.init_before_message()

        if preproc:
            message = self.preproc_user_input(user_message)
        else:
            message = user_message

        while message:
            self.reflected_message = None
            list(self.send_message(message))

            if not self.reflected_message:
                last_assistant_msg = self.done_messages[-1] if self.done_messages else None
                if last_assistant_msg and last_assistant_msg.get("role") == "assistant":
                    content = last_assistant_msg.get("content", "")
                    if "```mermaid" in content or "```html" in content or "```svg" in content:

                        def run_preview():
                            try:
                                from aider.skills.base import SkillContext, _run_async_safely

                                preview_skill = self.skills_registry.create(
                                    "artifact-preview",
                                    SkillContext(coder=self, io=self.io),
                                )
                                if preview_skill:
                                    _run_async_safely(preview_skill.execute(content))
                            except Exception as e:
                                self.io.tool_error(f"Artifact preview failed: {e}")

                        threading.Thread(target=run_preview, daemon=True).start()
                break

            if self.num_reflections >= self.max_reflections:
                self.io.tool_warning(f"Only {self.max_reflections} reflections allowed, stopping.")
                return

            self.num_reflections += 1
            message = self.reflected_message

    # ===== ASYNC METHODS (Option B - Persistent Prompt) =====

    async def run_async(self, with_message=None, preproc=True):
        """
        Asynchronous run method (Option B - Persistent Prompt).
        
        Enables non-blocking prompt input during generation. Key behaviors:
        - Tab during generation: Queue message for next turn
        - Enter during generation: Steer (cancel + new generation)
        - Escape: Cancel current generation
        
        This creates a true persistent prompt like kimi-cli where the user
        can always type, even while the AI is generating.
        """
        from aider.async_running_prompt import AsyncPromptDelegate
        
        # Get the async running prompt manager
        manager = self.io.async_running_prompt_manager
        delegate = AsyncPromptDelegate(manager, io=self.io)
        
        # Start live output for docked prompt
        self.io.start_live_output()
        
        try:
            if with_message:
                await self.io.display_user_input_async(with_message)
                await self.run_one_async(with_message, preproc)
                return self.partial_response_content
            
            # Main async loop with persistent prompt
            while True:
                try:
                    if not self.io.placeholder:
                        self.copy_context()
                    
                    # Check for queued messages first
                    if manager.has_queued_messages:
                        messages = manager.get_queued_messages()
                        for msg in messages:
                            await self.io.display_user_input_async(msg)
                            await self.run_one_async(msg, preproc)
                            self.show_undo_hint()
                        continue
                    
                    # Get input asynchronously
                    # Attach delegate so key bindings can detect generation state
                    if hasattr(self.io, 'async_prompt_session') and self.io.async_prompt_session:
                        self.io.async_prompt_session.attach_running_prompt(delegate)
                    delegate.activate()
                    
                    user_message = await self.get_input_async()
                    
                    delegate.deactivate()
                    if hasattr(self.io, 'async_prompt_session') and self.io.async_prompt_session:
                        self.io.async_prompt_session.detach_running_prompt()
                    
                    if not user_message:
                        continue
                    
                    # Check if it's a command
                    if self.commands.is_command(user_message):
                        result = self.commands.run(user_message)
                        if result:
                            continue
                    
                    # Run generation asynchronously using the manager
                    await manager.start_generation(
                        self._run_generation_task,
                        user_message,
                        preproc
                    )
                    
                    # Generation is now running in background
                    # Input loop continues immediately
                    
                except KeyboardInterrupt:
                    if manager.is_generating:
                        await manager.cancel()
                    else:
                        self.keyboard_interrupt()
        except EOFError:
            return
        finally:
            # Stop live output on exit
            self.io.stop_live_output()
    
    async def _run_generation_task(self, user_message: str, preproc: bool):
        """Task that runs generation in the background."""
        await self.run_one_async(user_message, preproc)
        self.show_undo_hint()

    async def get_input_async(self) -> str:
        """Get user input asynchronously."""
        inchat_files = self.get_inchat_relative_files()
        read_only_files = [self.get_rel_fname(fname) for fname in self.abs_read_only_fnames]
        all_files = sorted(set(inchat_files + read_only_files))
        edit_format = "" if self.edit_format == self.main_model.edit_format else self.edit_format
        
        # Use async version if available
        if hasattr(self.io, 'get_input_async'):
            return await self.io.get_input_async(
                self.root,
                all_files,
                self.get_addable_relative_files(),
                self.commands,
                self.abs_read_only_fnames,
                edit_format=edit_format,
            )
        # Fall back to sync version in thread
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get_input)

    async def run_one_async(self, user_message: str, preproc: bool):
        """Async version of run_one."""
        self.init_before_message()

        if preproc:
            message = self.preproc_user_input(user_message)
        else:
            message = user_message

        while message:
            self.reflected_message = None
            
            # Process send_message asynchronously
            # Convert generator to async
            await self._async_send_message_wrapper(message)

            if not self.reflected_message:
                last_assistant_msg = self.done_messages[-1] if self.done_messages else None
                if last_assistant_msg and last_assistant_msg.get("role") == "assistant":
                    content = last_assistant_msg.get("content", "")
                    if "```mermaid" in content or "```html" in content or "```svg" in content:
                        # Note: Preview is still threaded, not async
                        def run_preview():
                            try:
                                from aider.skills.base import SkillContext, _run_async_safely

                                preview_skill = self.skills_registry.create(
                                    "artifact-preview",
                                    SkillContext(coder=self, io=self.io),
                                )
                                if preview_skill:
                                    _run_async_safely(preview_skill.execute(content))
                            except Exception as e:
                                self.io.tool_error(f"Artifact preview failed: {e}")

                        threading.Thread(target=run_preview, daemon=True).start()
                break

            if self.num_reflections >= self.max_reflections:
                self.io.tool_warning(f"Only {self.max_reflections} reflections allowed, stopping.")
                return

            self.num_reflections += 1
            message = self.reflected_message

    async def _async_send_message_wrapper(self, message):
        """Wrap send_message generator for async streaming execution."""
        from aider.ui import ThinkingStateManager, AsyncSendMessageAdapter
        
        # Create thinking state manager
        def on_state_change(state):
            # Update docked prompt thinking state
            if hasattr(self.io, '_docked_prompt') and self.io._docked_prompt:
                is_thinking = state.name in ('THINKING', 'STREAMING', 'STARTING')
                self.io._docked_prompt.update_status(thinking=is_thinking)
        
        thinking_manager = ThinkingStateManager(on_state_change=on_state_change)
        
        # Create adapter for streaming
        adapter = AsyncSendMessageAdapter(
            self.send_message,
            thinking_manager=thinking_manager,
        )
        
        # Stream chunks asynchronously
        async for chunk in adapter.stream(message):
            # Chunk is yielded but send_message already handles output
            pass

    def check_and_open_urls(self, exc, friendly_msg=None):
        text = str(exc)

        if friendly_msg:
            self.io.tool_warning(text)
            self.io.tool_error(f"{friendly_msg}")
        else:
            self.io.tool_error(text)

        url_pattern = re.compile(r'(https?://[^\s/$.?#].[^\s"]*)')
        urls = list(set(url_pattern.findall(text)))
        for url in urls:
            url = url.rstrip(".',\"}")
            self.io.offer_url(url)
        return urls

    def check_for_urls(self, inp: str) -> str:
        if not self.detect_urls:
            return inp

        url_pattern = re.compile(r'(https?://[^\s/$.?#].[^\s"]*)')
        raw_urls = url_pattern.findall(inp)
        urls = list(set(u.rstrip(".',\"}") for u in raw_urls))
        group = ConfirmGroup(urls)
        for url in urls:
            if url not in self.rejected_urls:
                if self.io.confirm_ask(
                    "Add URL to the chat?", subject=url, group=group, allow_never=True
                ):
                    inp += "\n\n"
                    inp += self.commands.cmd_web(url, return_content=True)
                else:
                    self.rejected_urls.add(url)

        return inp

    def keyboard_interrupt(self):
        Console().show_cursor(True)

        now = time.time()

        thresh = 2
        if self.last_keyboard_interrupt and now - self.last_keyboard_interrupt < thresh:
            self.io.tool_warning("\n\n^C KeyboardInterrupt")
            self.event("exit", reason="Control-C")
            sys.exit()

        self.io.tool_warning("\n\n^C again to exit")

        self.last_keyboard_interrupt = now
