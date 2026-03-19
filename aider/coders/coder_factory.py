"""
Coder Factory - centralized creation logic for Coder instances.

This module contains the factory pattern implementation that reduces the 
responsibility of Coder.create() by delegating creation logic to a factory.
This improves separation of concerns and makes the creation process more testable.
"""

import logging
from typing import Optional, Dict, Any, List, Union

from aider import models
from aider.history import ChatSummary
from aider.io import InputOutput

logger = logging.getLogger(__name__)


class CoderCreationError(Exception):
    """Raised when coder creation fails."""
    pass


class CoderFactoryImpl:
    """
    Factory for creating Coder instances with proper dependency resolution.
    
    This factory handles the complex initialization logic that was previously
    embedded directly in Coder.create(), improving separation of concerns.
    """

    def __init__(self):
        self._coder_classes = None

    def _get_coder_classes(self):
        """Lazy load coder classes to avoid circular imports."""
        if self._coder_classes is None:
            import aider.coders as coders
            self._coder_classes = [
                c for c in coders.__all__
                if hasattr(c, "edit_format") and c.edit_format is not None
            ]
        return self._coder_classes

    def resolve_model(
        self,
        main_model=None,
        from_coder=None,
        default_model_name: str = None,
    ) -> tuple:
        """
        Resolve the main model from various sources.

        Returns:
            Tuple of (resolved_model, was_inherited)
        """
        if main_model is not None:
            return main_model, False
        if from_coder is not None:
            return from_coder.main_model, True
        if default_model_name is None:
            default_model_name = models.DEFAULT_MODEL_NAME
        return models.Model(default_model_name), False

    def resolve_edit_format(
        self,
        edit_format: Optional[str] = None,
        main_model=None,
        from_coder=None,
    ) -> tuple:
        """
        Resolve edit format from various sources.

        Returns:
            Tuple of (resolved_format, was_inherited)
        """
        if edit_format == "code":
            edit_format = None
        if edit_format is not None:
            return edit_format, False
        if from_coder is not None:
            return from_coder.edit_format, True
        if main_model is not None:
            return main_model.edit_format, True
        return "diff", False

    def resolve_io(self, io=None, from_coder=None) -> InputOutput:
        """Resolve IO from explicit value or source coder."""
        if io is not None:
            return io
        if from_coder is not None:
            return from_coder.io
        return InputOutput()

    def maybe_summarize_messages(
        self,
        from_coder,
        new_edit_format: str,
        io: InputOutput,
        summarize: bool = True,
    ) -> List[Dict]:
        """
        Summarize messages when edit format changes.
        """
        if from_coder is None:
            return []

        done_messages = from_coder.done_messages

        if new_edit_format == from_coder.edit_format:
            return done_messages

        if not done_messages or not summarize:
            return done_messages

        try:
            return from_coder.summarizer.summarize_all(done_messages)
        except ValueError:
            io.tool_warning(
                "Chat history summarization failed, continuing with full history"
            )
            return done_messages

    def build_kwargs(
        self,
        from_coder=None,
        edit_format: str = None,
        summarize_from_coder: bool = True,
        io: InputOutput = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Build the final kwargs for Coder initialization.
        """
        if from_coder is None:
            return dict(kwargs)

        use_kwargs = dict(from_coder.original_kwargs)

        done_messages = self.maybe_summarize_messages(
            from_coder, edit_format, io, summarize_from_coder
        )

        update = self._build_context_update(from_coder, done_messages)
        use_kwargs.update(update)
        use_kwargs.update(kwargs)

        from_coder.ok_to_warm_cache = False

        return use_kwargs

    def _build_context_update(self, from_coder, done_messages) -> Dict[str, Any]:
        """Build the context transfer dict from source coder."""
        return dict(
            fnames=list(from_coder.abs_fnames),
            read_only_fnames=list(from_coder.abs_read_only_fnames),
            done_messages=done_messages,
            cur_messages=from_coder.cur_messages,
            runtime=from_coder.runtime,
            analytics=from_coder.analytics,
            aider_commit_hashes=from_coder.aider_commit_hashes,
            commands=from_coder.commands.clone(),
            total_cost=from_coder.total_cost,
            ignore_mentions=from_coder.ignore_mentions,
            total_tokens_sent=from_coder.total_tokens_sent,
            total_tokens_received=from_coder.total_tokens_received,
            file_watcher=from_coder.file_watcher,
            system_prompt_override=from_coder.system_prompt_override,
        )

    def find_coder_class(self, edit_format: str):
        """Find the appropriate coder class for the given edit format."""
        import aider.coders as coders
        
        for coder_class in coders.__all__:
            if hasattr(coder_class, "edit_format") and coder_class.edit_format == edit_format:
                return coder_class

        valid_formats = [
            str(c.edit_format) for c in self._get_coder_classes()
        ]
        raise UnknownEditFormat(edit_format, valid_formats)

    def create(
        self,
        main_model=None,
        edit_format=None,
        io=None,
        from_coder=None,
        summarize_from_coder=True,
        **kwargs
    ):
        """
        Create a Coder instance with proper dependency resolution.
        """
        resolved_model, _ = self.resolve_model(main_model, from_coder)
        resolved_format, _ = self.resolve_edit_format(edit_format, resolved_model, from_coder)
        resolved_io = self.resolve_io(io, from_coder)

        final_kwargs = self.build_kwargs(
            from_coder=from_coder,
            edit_format=resolved_format,
            summarize_from_coder=summarize_from_coder,
            io=resolved_io,
            **kwargs
        )

        coder_class = self.find_coder_class(resolved_format)
        instance = coder_class(resolved_model, resolved_io, **final_kwargs)
        instance.original_kwargs = dict(final_kwargs)

        return instance


# Re-export for compatibility
class UnknownEditFormat(ValueError):
    def __init__(self, edit_format, valid_formats):
        self.edit_format = edit_format
        self.valid_formats = valid_formats
        super().__init__(
            f"Unknown edit format {edit_format}. Valid formats are: {', '.join(valid_formats)}"
        )


# Backward compatibility alias
CoderFactory = CoderFactoryImpl


# Global factory instance for convenience
_default_factory = None


def get_coder_factory():
    """Get the global CoderFactory instance."""
    global _default_factory
    if _default_factory is None:
        _default_factory = CoderFactoryImpl()
    return _default_factory


def create_coder(
    main_model=None,
    edit_format=None,
    io=None,
    from_coder=None,
    summarize_from_coder=True,
    **kwargs
):
    """
    Convenience function to create a Coder using the global factory.
    """
    factory = get_coder_factory()
    return factory.create(
        main_model=main_model,
        edit_format=edit_format,
        io=io,
        from_coder=from_coder,
        summarize_from_coder=summarize_from_coder,
        **kwargs
    )
