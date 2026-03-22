"""Circuit breakers and rate limiting for resilient tool execution."""

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import wraps
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states.

    State Machine:

        ┌─────────────┐
        │   CLOSED    │◄────────────────────────┐
        │  (normal)   │                         │
        └──────┬──────┘                         │
               │                                │
               │ failure_threshold reached      │ success_threshold reached
               ▼                                │ (half_open_calls succeeded)
        ┌─────────────┐                         │
        │    OPEN     │─────────────────────────┘
        │  (failing)  │  recovery_timeout expires
        └──────┬──────┘  ───────────────────────►┌─────────────┐
                                                 │  HALF_OPEN  │
                                                 │  (testing)  │
                                                 └─────────────┘
    """

    CLOSED = auto()  # Normal operation - requests pass through
    OPEN = auto()  # Failing - rejecting requests immediately
    HALF_OPEN = auto()  # Testing - allowing limited requests through


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is OPEN and rejecting requests."""

    pass


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    pass


@dataclass
class CircuitBreakerMetrics:
    """Metrics for circuit breaker monitoring."""

    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    rejected_calls: int = 0  # Calls rejected due to OPEN state
    state_transitions: Dict[CircuitState, int] = field(
        default_factory=lambda: {
            CircuitState.CLOSED: 0,
            CircuitState.OPEN: 0,
            CircuitState.HALF_OPEN: 0,
        }
    )
    last_state_change: float = 0.0
    consecutive_successes: int = 0
    consecutive_failures: int = 0

    def record_transition(self, new_state: CircuitState):
        """Record a state transition."""
        self.state_transitions[new_state] += 1
        self.last_state_change = time.time()


@dataclass
class CircuitBreaker:
    """
    Circuit breaker pattern implementation.

    Prevents cascade failures by stopping requests to failing services.
    Uses a state machine with three states:

    - CLOSED: Normal operation, requests pass through
    - OPEN: Service is failing, requests are rejected immediately
    - HALF_OPEN: Testing if service has recovered, limited requests allowed

    Thread-safe for concurrent access using reentrant lock.

    Example:
        breaker = CircuitBreaker(name="api_calls", failure_threshold=5)

        try:
            result = breaker.call(make_api_request, url)
        except CircuitBreakerOpen:
            # Circuit is open, use fallback
            result = cached_result
    """

    name: str
    failure_threshold: int = 5
    success_threshold: int = 2  # Successes needed in HALF_OPEN to close
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3

    # State (initialized as CLOSED)
    state: CircuitState = field(default=CircuitState.CLOSED, repr=True)
    failure_count: int = field(default=0, repr=False)
    success_count: int = field(default=0, repr=False)
    last_failure_time: float = field(default=0.0, repr=False)
    half_open_calls: int = field(default=0, repr=False)

    # Thread safety
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    # Metrics
    metrics: CircuitBreakerMetrics = field(default_factory=CircuitBreakerMetrics, repr=False)

    def __post_init__(self):
        """Initialize metrics state tracking."""
        self.metrics.last_state_change = time.time()

    def call(self, operation: Callable, *args, **kwargs) -> Any:
        """
        Execute operation with circuit breaker protection.

        Args:
            operation: Callable to execute
            *args, **kwargs: Arguments for operation

        Returns:
            Result from operation

        Raises:
            CircuitBreakerOpen: If circuit is OPEN
            Exception: Any exception from operation (after recording failure)
        """
        with self._lock:
            self.metrics.total_calls += 1

            # State machine check before executing
            if self.state == CircuitState.OPEN:
                # Check if recovery timeout has passed
                if time.time() - self.last_failure_time >= self.recovery_timeout:
                    # Transition to HALF_OPEN to test recovery
                    self._transition_to_half_open()
                else:
                    # Still in recovery period, reject immediately
                    self.metrics.rejected_calls += 1
                    logger.warning(
                        f"CircuitBreaker[{self.name}]: REJECTING call - circuit OPEN "
                        f"({time.time() - self.last_failure_time:.1f}s since failure)"
                    )
                    raise CircuitBreakerOpen(
                        f"Circuit breaker '{self.name}' is OPEN. "
                        f"Try again after recovery timeout ({self.recovery_timeout}s)"
                    )

            elif self.state == CircuitState.HALF_OPEN:
                # In half-open, limit concurrent test calls
                if self.half_open_calls >= self.half_open_max_calls:
                    self.metrics.rejected_calls += 1
                    logger.warning(
                        f"CircuitBreaker[{self.name}]: REJECTING call - max half-open calls reached"
                    )
                    raise CircuitBreakerOpen(
                        f"Circuit breaker '{self.name}' is HALF_OPEN - "
                        f"max test calls ({self.half_open_max_calls}) reached"
                    )

                self.half_open_calls += 1

            # CLOSED state: proceed normally

        # Execute outside lock to allow concurrent operations in CLOSED state
        try:
            result = operation(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise
        finally:
            # Decrement half-open counter if we were testing
            with self._lock:
                if self.state == CircuitState.HALF_OPEN:
                    self.half_open_calls = max(0, self.half_open_calls - 1)

    def record_success(self):
        """
        Record successful operation.

        In CLOSED: Resets failure count
        In HALF_OPEN: Counts toward closing the circuit
        """
        with self._lock:
            self.metrics.successful_calls += 1
            self.metrics.consecutive_successes += 1
            self.metrics.consecutive_failures = 0

            if self.state == CircuitState.CLOSED:
                # Normal success: reset failure counter
                self.failure_count = 0

            elif self.state == CircuitState.HALF_OPEN:
                # Test call succeeded: increment success count
                self.success_count += 1
                logger.info(
                    f"CircuitBreaker[{self.name}]: HALF_OPEN success "
                    f"({self.success_count}/{self.success_threshold})"
                )

                if self.success_count >= self.success_threshold:
                    # Enough successes, close the circuit
                    self._transition_to_closed()

    def record_failure(self):
        """
        Record failed operation.

        In CLOSED: Increments failure count, may trip to OPEN
        In HALF_OPEN: Immediately returns to OPEN
        """
        with self._lock:
            self.metrics.failed_calls += 1
            self.metrics.consecutive_failures += 1
            self.metrics.consecutive_successes = 0
            self.last_failure_time = time.time()

            if self.state == CircuitState.CLOSED:
                # Normal operation failure
                self.failure_count += 1
                logger.warning(
                    f"CircuitBreaker[{self.name}]: FAILURE recorded "
                    f"({self.failure_count}/{self.failure_threshold})"
                )

                if self.failure_count >= self.failure_threshold:
                    # Too many failures, trip the circuit
                    self._transition_to_open()

            elif self.state == CircuitState.HALF_OPEN:
                # Test call failed, service not recovered
                logger.warning(
                    f"CircuitBreaker[{self.name}]: HALF_OPEN test FAILED, returning to OPEN"
                )
                self._transition_to_open()

    def _transition_to_open(self):
        """
        Trip circuit to OPEN state.

        All subsequent calls will be rejected until recovery timeout.
        """
        old_state = self.state
        self.state = CircuitState.OPEN
        self.metrics.record_transition(CircuitState.OPEN)
        logger.error(
            f"CircuitBreaker[{self.name}]: State transition {old_state.name} -> OPEN "
            f"({self.failure_count} failures, threshold={self.failure_threshold})"
        )

    def _transition_to_half_open(self):
        """
        Test recovery with HALF_OPEN state.

        Allows limited test calls to check if service recovered.
        """
        old_state = self.state
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.half_open_calls = 0
        self.metrics.record_transition(CircuitState.HALF_OPEN)
        logger.info(
            f"CircuitBreaker[{self.name}]: State transition {old_state.name} -> HALF_OPEN "
            f"(testing recovery after {self.recovery_timeout}s timeout)"
        )

    def _transition_to_closed(self):
        """
        Restore normal operation.

        Circuit is healthy again, reset all counters.
        """
        old_state = self.state
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.half_open_calls = 0
        self.metrics.record_transition(CircuitState.CLOSED)
        logger.info(
            f"CircuitBreaker[{self.name}]: State transition {old_state.name} -> CLOSED "
            f"(circuit healthy, {self.success_threshold} consecutive successes)"
        )

    def get_state(self) -> CircuitState:
        """Get current circuit state (thread-safe)."""
        with self._lock:
            return self.state

    def reset(self):
        """Manually reset circuit to CLOSED state."""
        with self._lock:
            old_state = self.state
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.half_open_calls = 0
            self.metrics.record_transition(CircuitState.CLOSED)
            logger.info(f"CircuitBreaker[{self.name}]: MANUAL RESET {old_state.name} -> CLOSED")

    def __call__(self, operation: Callable) -> Callable:
        """Decorator support: @circuit_breaker.call def my_func(): ..."""

        @wraps(operation)
        def wrapper(*args, **kwargs):
            return self.call(operation, *args, **kwargs)

        return wrapper


@dataclass
class TokenBucket:
    """
    Token bucket rate limiter.

    Allows bursts up to capacity, then limits to steady rate.
    Thread-safe for concurrent access.

    Algorithm:
    - Bucket has fixed capacity (max burst size)
    - Tokens added at constant rate
    - Request consumes tokens if available
    - If not enough tokens, request is rejected (or can wait)

    Example:
        bucket = TokenBucket(rate=10, capacity=20)  # 10/sec, burst 20

        if bucket.consume():
            make_request()
        else:
            # Rate limited
            pass
    """

    rate: float  # tokens per second
    capacity: float  # max burst

    _tokens: float = field(default=0.0, repr=False)
    _last_update: float = field(default_factory=time.time, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def __post_init__(self):
        """Initialize bucket to full capacity."""
        self._tokens = self.capacity

    def _add_tokens(self):
        """Add tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self._last_update
        self._last_update = now

        # Add tokens at rate, capped at capacity
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)

    def consume(
        self, tokens: float = 1.0, block: bool = False, timeout: Optional[float] = None
    ) -> bool:
        """
        Try to consume tokens.

        Args:
            tokens: Number of tokens to consume
            block: If True, wait until tokens available
            timeout: Max seconds to wait if blocking

        Returns:
            True if tokens were consumed, False otherwise
        """
        if block:
            return self._consume_blocking(tokens, timeout)

        with self._lock:
            self._add_tokens()

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def _consume_blocking(self, tokens: float, timeout: Optional[float]) -> bool:
        """Block until tokens available or timeout."""
        start_time = time.time()

        while True:
            with self._lock:
                self._add_tokens()

                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True

                # Calculate wait time
                tokens_needed = tokens - self._tokens
                wait_time = tokens_needed / self.rate

                if timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed + wait_time > timeout:
                        return False

            # Release lock while sleeping
            time.sleep(min(wait_time, 0.1))  # Max 100ms sleeps to check timeout

    def get_wait_time(self, tokens: float = 1.0) -> float:
        """
        Get seconds to wait before tokens available.

        Returns 0 if tokens are available now.
        """
        with self._lock:
            self._add_tokens()

            if self._tokens >= tokens:
                return 0.0

            tokens_needed = tokens - self._tokens
            return tokens_needed / self.rate

    def get_available_tokens(self) -> float:
        """Get current number of available tokens."""
        with self._lock:
            self._add_tokens()
            return self._tokens


@dataclass
class ExponentialBackoff:
    """
    Exponential backoff with jitter.

    Prevents thundering herd on recovery by adding randomization.

    Formula:
        delay = min(base_delay * (exponential_base ^ attempt), max_delay)
        if jitter: delay = random.uniform(0, delay)

    Example:
        backoff = ExponentialBackoff(base_delay=1.0, max_delay=60.0, max_retries=5)

        for attempt in range(backoff.max_retries):
            try:
                result = operation()
                break
            except Exception:
                backoff.sleep(attempt)
        else:
            raise MaxRetriesExceeded()
    """

    base_delay: float = 1.0
    max_delay: float = 60.0
    max_retries: int = 5
    exponential_base: float = 2.0
    jitter: bool = True
    jitter_max_ratio: float = 0.25  # Max 25% jitter

    def get_delay(self, attempt: int) -> float:
        """
        Get delay for attempt number (0-indexed).

        Args:
            attempt: Retry attempt number (0 = first retry)

        Returns:
            Seconds to delay
        """
        # Calculate exponential delay
        delay = self.base_delay * (self.exponential_base**attempt)
        delay = min(delay, self.max_delay)

        if self.jitter:
            # Add random jitter: delay * (1 - jitter_max_ratio to 1)
            jitter_factor = random.uniform(1 - self.jitter_max_ratio, 1.0)
            delay = delay * jitter_factor

        return delay

    def sleep(self, attempt: int):
        """Sleep for appropriate delay."""
        delay = self.get_delay(attempt)
        time.sleep(delay)

    def retry(self, operation: Callable, *args, **kwargs) -> Any:
        """
        Execute operation with retry.

        Args:
            operation: Callable to retry
            *args, **kwargs: Arguments for operation

        Returns:
            Result from successful operation

        Raises:
            Exception: Last exception after all retries exhausted
        """
        last_exception = None

        for attempt in range(self.max_retries):
            try:
                return operation(*args, **kwargs)
            except Exception as e:
                last_exception = e

                if attempt < self.max_retries - 1:
                    logger.warning(
                        f"Operation failed (attempt {attempt + 1}/{self.max_retries}): {e}. "
                        "Retrying..."
                    )
                    self.sleep(attempt)
                else:
                    logger.error(f"Operation failed after {self.max_retries} attempts: {e}")

        raise last_exception


@dataclass
class ResilientExecutor:
    """
    Combines circuit breaker, rate limiting, and retry logic.

    The complete resilience pattern for tool execution.

    Execution flow:
    1. Check circuit breaker state
    2. Wait for rate limiter if needed
    3. Execute with exponential backoff retry
    4. Record success/failure to circuit breaker

    Example:
        executor = ResilientExecutor(
            circuit_breaker=CircuitBreakers.llm_api(),
            rate_limiter=RateLimiters.llm_api(),
            backoff=ExponentialBackoff(max_retries=3)
        )

        result = executor.execute(call_llm, prompt)
    """

    circuit_breaker: CircuitBreaker
    rate_limiter: TokenBucket
    backoff: ExponentialBackoff
    fail_fast_on_rate_limit: bool = False  # If True, don't retry rate limit errors
    _last_retry_count: int = 0  # Track retries from last execution

    @property
    def last_retry_count(self) -> int:
        """Get the number of retries from the last execution."""
        return self._last_retry_count

    def execute(self, operation: Callable, *args, **kwargs) -> Any:
        """
        Execute with full resilience patterns.

        Args:
            operation: Callable to execute
            *args, **kwargs: Arguments for operation

        Returns:
            Result from operation

        Raises:
            CircuitBreakerOpen: If circuit is open
            Exception: After all retries exhausted
        """
        # Step 1: Check circuit breaker (raises CircuitBreakerOpen if OPEN)
        # We do this before acquiring rate limit tokens to avoid wasting them
        with self.circuit_breaker._lock:
            current_state = self.circuit_breaker.state

            if current_state == CircuitState.OPEN:
                # Check if should transition to HALF_OPEN
                if (
                    time.time() - self.circuit_breaker.last_failure_time
                    >= self.circuit_breaker.recovery_timeout
                ):
                    self.circuit_breaker._transition_to_half_open()
                else:
                    self.circuit_breaker.metrics.rejected_calls += 1
                    raise CircuitBreakerOpen(f"Circuit '{self.circuit_breaker.name}' is OPEN")

        # Step 2: Wait for rate limiter
        # Use blocking consume to wait for tokens
        if not self.rate_limiter.consume(block=True, timeout=30.0):
            raise RateLimitExceeded(
                f"Rate limit timeout waiting for tokens (bucket: {self.rate_limiter.rate}/sec)"
            )

        # Step 3: Execute with retry
        last_exception = None
        self._last_retry_count = 0  # Reset retry count

        for attempt in range(self.backoff.max_retries):
            try:
                result = operation(*args, **kwargs)
                # Success: record and return
                self.circuit_breaker.record_success()
                self._last_retry_count = attempt  # Record actual retries
                return result

            except CircuitBreakerOpen:
                # Don't retry circuit breaker open
                self._last_retry_count = attempt
                raise

            except RateLimitExceeded:
                if self.fail_fast_on_rate_limit:
                    self._last_retry_count = attempt
                    raise
                # Otherwise retry with backoff
                last_exception = RateLimitExceeded("Rate limit hit")

            except Exception as e:
                last_exception = e
                # Record failure in circuit breaker
                self.circuit_breaker.record_failure()

                # Check if circuit breaker is now open
                if self.circuit_breaker.get_state() == CircuitState.OPEN:
                    self._last_retry_count = attempt
                    raise CircuitBreakerOpen(
                        f"Circuit '{self.circuit_breaker.name}' opened after failure: {e}"
                    ) from e

            # Retry with backoff (unless last attempt)
            if attempt < self.backoff.max_retries - 1:
                logger.warning(
                    f"ResilientExecutor[{self.circuit_breaker.name}]: "
                    f"Attempt {attempt + 1} failed, retrying..."
                )
                self.backoff.sleep(attempt)

        # All retries exhausted
        self._last_retry_count = self.backoff.max_retries - 1
        raise last_exception if last_exception else Exception("All retries failed")

    def __call__(self, operation: Callable) -> Callable:
        """Decorator support."""

        @wraps(operation)
        def wrapper(*args, **kwargs):
            return self.execute(operation, *args, **kwargs)

        return wrapper


# Pre-configured breakers for different services
class CircuitBreakers:
    """Factory for common circuit breaker configurations."""

    @staticmethod
    def llm_api() -> CircuitBreaker:
        """
        For LLM API calls (higher thresholds, longer timeout).

        LLM APIs can be slow and occasionally fail due to:
        - Rate limiting from provider
        - Temporary service degradation
        - Network hiccups

        Use higher thresholds to avoid unnecessary circuit breaking.
        """
        return CircuitBreaker(
            name="llm_api",
            failure_threshold=3,
            success_threshold=2,
            recovery_timeout=60.0,
            half_open_max_calls=2,
        )

    @staticmethod
    def tool_execution() -> CircuitBreaker:
        """
        For tool execution (lower thresholds, faster recovery).

        Tool executions that fail are often due to:
        - Invalid user input
        - Resource constraints
        - Permission issues

        Use lower thresholds to fail fast and recover quickly.
        """
        return CircuitBreaker(
            name="tool_execution",
            failure_threshold=2,
            success_threshold=1,
            recovery_timeout=10.0,
            half_open_max_calls=1,
        )

    @staticmethod
    def external_api() -> CircuitBreaker:
        """
        For external API calls (balanced thresholds).

        General-purpose external services.
        """
        return CircuitBreaker(
            name="external_api",
            failure_threshold=5,
            success_threshold=2,
            recovery_timeout=30.0,
            half_open_max_calls=2,
        )

    @staticmethod
    def database() -> CircuitBreaker:
        """
        For database operations (higher thresholds).

        Database connections should be stable.
        Only trip on persistent failures.
        """
        return CircuitBreaker(
            name="database",
            failure_threshold=10,
            success_threshold=3,
            recovery_timeout=30.0,
            half_open_max_calls=3,
        )


# Pre-configured rate limiters for different services
class RateLimiters:
    """Factory for common rate limiter configurations."""

    @staticmethod
    def llm_api(requests_per_second: float = 2.0, burst: int = 5) -> TokenBucket:
        """
        For LLM API calls.

        Default: 2 req/sec with burst of 5 for initial requests.
        Adjust based on your API tier limits.
        """
        return TokenBucket(rate=requests_per_second, capacity=burst)

    @staticmethod
    def aggressive(rate: float = 10.0, capacity: int = 20) -> TokenBucket:
        """For high-throughput internal operations."""
        return TokenBucket(rate=rate, capacity=capacity)

    @staticmethod
    def conservative(rate: float = 1.0, capacity: int = 2) -> TokenBucket:
        """For expensive or rate-limited external services."""
        return TokenBucket(rate=rate, capacity=capacity)

    @staticmethod
    def burst_only(capacity: int = 10) -> TokenBucket:
        """
        For operations that can burst but shouldn't sustain.

        Very low sustained rate (0.1/sec) but allows bursts.
        """
        return TokenBucket(rate=0.1, capacity=capacity)


# Pre-configured backoff strategies
class BackoffStrategies:
    """Factory for common exponential backoff configurations."""

    @staticmethod
    def aggressive() -> ExponentialBackoff:
        """Fast retry for quick recovery (e.g., local services)."""
        return ExponentialBackoff(
            base_delay=0.1, max_delay=5.0, max_retries=5, exponential_base=2.0
        )

    @staticmethod
    def standard() -> ExponentialBackoff:
        """Standard retry for most operations."""
        return ExponentialBackoff(
            base_delay=1.0, max_delay=60.0, max_retries=3, exponential_base=2.0
        )

    @staticmethod
    def patient() -> ExponentialBackoff:
        """Slow retry for rate-limited or expensive operations."""
        return ExponentialBackoff(
            base_delay=2.0, max_delay=300.0, max_retries=10, exponential_base=2.0  # 5 minutes
        )

    @staticmethod
    def no_jitter() -> ExponentialBackoff:
        """Deterministic retry without jitter (for testing)."""
        return ExponentialBackoff(base_delay=1.0, max_delay=60.0, max_retries=3, jitter=False)


# Convenience functions
def with_resilience(
    circuit_name: str = "default",
    failure_threshold: int = 5,
    rate: float = 10.0,
    max_retries: int = 3,
):
    """
    Decorator factory for adding resilience to functions.

    Example:
        @with_resilience(circuit_name="api", rate=5.0)
        def call_api(url):
            return requests.get(url, timeout=10)
    """
    breaker = CircuitBreaker(name=circuit_name, failure_threshold=failure_threshold)
    limiter = TokenBucket(rate=rate, capacity=rate * 2)
    backoff = ExponentialBackoff(max_retries=max_retries)
    executor = ResilientExecutor(breaker, limiter, backoff)

    return executor


# Global registry for shared circuit breakers
_circuit_breakers: Dict[str, CircuitBreaker] = {}
_circuit_breakers_lock = threading.Lock()


def get_circuit_breaker(name: str) -> Optional[CircuitBreaker]:
    """Get a shared circuit breaker by name."""
    with _circuit_breakers_lock:
        return _circuit_breakers.get(name)


def register_circuit_breaker(breaker: CircuitBreaker) -> CircuitBreaker:
    """Register a circuit breaker for shared use."""
    with _circuit_breakers_lock:
        _circuit_breakers[breaker.name] = breaker
    return breaker
