import re
from dataclasses import dataclass

from aider.dump import dump  # noqa: F401


@dataclass
class ExInfo:
    name: str
    retry: bool
    description: str


EXCEPTIONS = [
    ExInfo("APIConnectionError", True, None),
    ExInfo("APIError", True, None),
    ExInfo("APIResponseValidationError", True, None),
    ExInfo(
        "AuthenticationError",
        False,
        "Authentication failed. Check your API key or credentials.",
    ),
    ExInfo("AzureOpenAIError", True, None),
    ExInfo("BadGatewayError", True, "The API provider's servers are down or overloaded."),
    ExInfo("BadRequestError", False, None),
    ExInfo("BudgetExceededError", True, None),
    ExInfo(
        "ContentPolicyViolationError",
        True,
        "The API provider has refused the request due to a safety policy about the content.",
    ),
    ExInfo("ContextWindowExceededError", False, None),  # special case handled in base_coder
    ExInfo("ImageFetchError", False, "The API provider was unable to fetch one or more images."),
    ExInfo("InternalServerError", True, "The API provider's servers are down or overloaded."),
    ExInfo("InvalidRequestError", True, None),
    ExInfo("JSONSchemaValidationError", True, None),
    ExInfo("NotFoundError", False, None),
    ExInfo(
        "PermissionDeniedError",
        False,
        "Permission was denied. Check your API key and/or credentials.",
    ),
    ExInfo("OpenAIError", True, None),
    ExInfo(
        "RateLimitError",
        True,
        "Rate limit hit. Waiting before retry...",
    ),
    ExInfo("RouterRateLimitError", True, None),
    ExInfo("ServiceUnavailableError", True, "The API provider's servers are down or overloaded."),
    ExInfo("UnprocessableEntityError", True, None),
    ExInfo("UnsupportedParamsError", True, None),
    ExInfo(
        "Timeout",
        True,
        "The API provider timed out without returning a response. They may be down or overloaded.",
    ),
]


class LiteLLMExceptions:
    exceptions = dict()
    exception_info = {exi.name: exi for exi in EXCEPTIONS}

    def __init__(self):
        self._load()

    def _load(self, strict=False):
        import litellm

        for var in dir(litellm):
            # Filter by BaseException because instances of non-exception classes cannot be caught.
            # `litellm.ErrorEventError` is an example of a regular class which just happens to end
            # with `Error`.
            if var.endswith("Error") and issubclass(getattr(litellm, var), BaseException):
                if var not in self.exception_info:
                    raise ValueError(f"{var} is in litellm but not in aider's exceptions list")

        for var in self.exception_info:
            ex = getattr(litellm, var)
            self.exceptions[ex] = self.exception_info[var]

    def exceptions_tuple(self):
        return tuple(self.exceptions)

    def get_ex_info(self, ex):
        """Return the ExInfo for a given exception instance"""
        import litellm

        if ex.__class__ is litellm.APIConnectionError:
            if "boto3" in str(ex):
                return ExInfo("APIConnectionError", False, "You need to: pip install boto3")
            if "OpenrouterException" in str(ex) and "'choices'" in str(ex):
                return ExInfo(
                    "APIConnectionError",
                    True,
                    (
                        "OpenRouter or the upstream API provider is down, overloaded or rate"
                        " limiting your requests."
                    ),
                )

        # Check for specific non-retryable APIError cases like insufficient credits
        if ex.__class__ is litellm.APIError:
            err_str = str(ex).lower()
            if "insufficient credits" in err_str and '"code":402' in err_str:
                return ExInfo(
                    "APIError",
                    False,
                    "Insufficient credits with the API provider. Please add credits.",
                )
            # Fall through to default APIError handling if not the specific credits error

        # Enhance RateLimitError with provider-specific guidance
        if ex.__class__ is litellm.RateLimitError:
            help_msg = self.get_rate_limit_help(str(ex))
            return ExInfo("RateLimitError", True, help_msg)

        # Enhance AuthenticationError with provider-specific guidance
        if ex.__class__ is litellm.AuthenticationError:
            err_str = str(ex).lower()
            if "openai" in err_str:
                return ExInfo(
                    "AuthenticationError",
                    False,
                    "OpenAI API key invalid. Set OPENAI_API_KEY environment variable.",
                )
            if "anthropic" in err_str or "claude" in err_str:
                return ExInfo(
                    "AuthenticationError",
                    False,
                    "Anthropic API key invalid. Set ANTHROPIC_API_KEY environment variable.",
                )
            if "gemini" in err_str or "google" in err_str:
                return ExInfo(
                    "AuthenticationError",
                    False,
                    "Google API key invalid. Set GEMINI_API_KEY or GOOGLE_API_KEY environment variable.",
                )
            if "openrouter" in err_str:
                return ExInfo(
                    "AuthenticationError",
                    False,
                    "OpenRouter API key invalid. Set OPENROUTER_API_KEY environment variable.",
                )

        return self.exceptions.get(ex.__class__, ExInfo(None, None, None))

    # Pre-compile regex for performance
    _RETRY_AFTER_RE = re.compile(r'retry[_-]?after[:\s]*(\d+)', re.IGNORECASE)

    def get_rate_limit_help(self, err_str: str) -> str:
        """Get provider-specific help for rate limit errors."""
        err_lower = err_str.lower()
        
        # Extract retry-after if available
        retry_match = self._RETRY_AFTER_RE.search(err_str)
        if retry_match:
            seconds = int(retry_match.group(1))
            if seconds < 60:
                return f"Rate limit: Retry after {seconds}s"
            else:
                mins = seconds // 60
                return f"Rate limit: Retry after {mins}m {seconds % 60}s"
        
        # Provider-specific guidance
        if "openrouter" in err_lower:
            return "OpenRouter rate limit. Try: 1) Add credits, 2) Wait 1min, 3) Check limits at openrouter.ai"
        if "anthropic" in err_lower or "claude" in err_lower:
            return "Anthropic rate limit. Try: 1) Wait 1min, 2) Check limits at console.anthropic.com"
        if "openai" in err_lower:
            return "OpenAI rate limit. Try: 1) Wait 1min, 2) Check usage at platform.openai.com"
        if "gemini" in err_lower or "google" in err_lower:
            return "Google rate limit. Try: 1) Wait 1min, 2) Check quotas at ai.google.dev"
        
        return "Rate limit hit. Waiting before retry..."
