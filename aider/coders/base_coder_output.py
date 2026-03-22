import math

from aider.llm import litellm
from aider.reasoning_tags import remove_reasoning_content, replace_reasoning_tags
from aider.utils import format_tokens


class BaseCoderOutputMixin:
    """Incremental response rendering and usage-report helpers."""

    # Token caching statistics (accumulated across all messages)
    total_cache_hit_tokens = 0
    total_cache_write_tokens = 0
    total_uncached_input_tokens = 0

    def get_token_cache_summary(self):
        """Generate a detailed token caching summary report.
        
        Returns a formatted string showing cache efficiency and savings,
        similar to Gemini's interaction summary.
        
        Example output:
            ╭──────────────────────────────────────────────────────────────╮
            │                    TOKEN CACHE SUMMARY                       │
            ╰──────────────────────────────────────────────────────────────╯
            
            Model                    Reqs   Input Tokens   Cache Reads   Output
            ─────────────────────────────────────────────────────────────────────
            claude-3-5-sonnet        12        128,358      1,234,567      45,230
            
            Savings Highlight: 1,234,567 (90.6%) of input tokens were served 
            from the cache, reducing costs.
            
            Cost Analysis:
              Uncached input cost:    $0.3204
              Cached input cost:      $0.0185  (94% cheaper)
              Output cost:            $0.6784
              ─────────────────────────────────
              Total cost:             $1.0173
              Cost without cache:     $2.7854
              Savings:                $1.7681  (63.5%)
        """
        total_input = self.total_uncached_input_tokens + self.total_cache_hit_tokens
        if total_input == 0:
            return None
        
        # Calculate percentages
        cache_percentage = (self.total_cache_hit_tokens / total_input) * 100 if total_input > 0 else 0
        
        # Get pricing info
        input_cost_per_token = self.main_model.info.get("input_cost_per_token") or 0
        cache_hit_cost_per_token = self.main_model.info.get("input_cost_per_token_cache_hit") or 0
        output_cost_per_token = self.main_model.info.get("output_cost_per_token") or 0
        
        # Calculate costs
        uncached_cost = self.total_uncached_input_tokens * input_cost_per_token
        
        if cache_hit_cost_per_token and cache_hit_cost_per_token > 0:
            cached_cost = self.total_cache_hit_tokens * cache_hit_cost_per_token
        elif input_cost_per_token > 0:
            # Default: cache hits cost ~10% of normal input (common for Anthropic)
            cached_cost = self.total_cache_hit_tokens * input_cost_per_token * 0.10
        else:
            cached_cost = 0
            
        # Calculate what cached tokens would have cost at full price
        normal_cost_for_cached = self.total_cache_hit_tokens * input_cost_per_token
        
        # Total output cost (approximate since we don't track separately)
        output_cost = self.total_cost - uncached_cost - cached_cost
        if output_cost < 0:
            output_cost = 0
            
        total_cost = self.total_cost
        cost_without_cache = total_cost + normal_cost_for_cached - cached_cost
        savings = cost_without_cache - total_cost
        savings_percentage = (savings / cost_without_cache) * 100 if cost_without_cache > 0 else 0
        
        lines = [
            "",
            "╭" + "─" * 62 + "╮",
            "│" + "TOKEN CACHE SUMMARY".center(62) + "│",
            "╰" + "─" * 62 + "╯",
            "",
        ]
        
        # Show model usage table if we have data
        if self.total_tokens_sent > 0 or self.total_tokens_received > 0:
            lines.extend([
                f"{'Model':<25} {'Reqs':>6} {'Input Tokens':>14} {'Cache Reads':>12}",
                "─" * 62,
                f"{self.main_model.name:<25} {'—':>6} {total_input:>14,} {self.total_cache_hit_tokens:>12,}",
                "",
            ])
        
        # Show savings highlight (like Gemini)
        if self.total_cache_hit_tokens > 0:
            lines.append(
                f"💰 Savings Highlight: {self.total_cache_hit_tokens:,} "
                f"({cache_percentage:.1f}%) of input tokens were served from the cache, "
                f"reducing costs."
            )
            lines.append("")
        
        # Show detailed cost analysis if we have pricing
        if input_cost_per_token > 0 and total_cost > 0:
            lines.extend([
                "Cost Analysis:",
                f"  Uncached input cost:    ${uncached_cost:>10.4f}",
            ])
            
            if self.total_cache_hit_tokens > 0:
                cache_discount = ((input_cost_per_token - (cache_hit_cost_per_token or input_cost_per_token * 0.10)) / input_cost_per_token * 100) if input_cost_per_token > 0 else 90
                lines.append(f"  Cached input cost:      ${cached_cost:>10.4f}  ({cache_discount:.0f}% cheaper)")
                
            lines.extend([
                f"  Total cost:             ${total_cost:>10.4f}",
            ])
            
            if savings > 0.0001:
                lines.extend([
                    f"  Cost without cache:     ${cost_without_cache:>10.4f}",
                    f"  You saved:              ${savings:>10.4f}  ({savings_percentage:.1f}%)",
                ])
            
            lines.append("")
        
        lines.append("─" * 62)
        
        return "\n".join(lines)

    def show_token_cache_summary(self):
        """Display the token cache summary if there's cache activity."""
        summary = self.get_token_cache_summary()
        if summary:
            self.io.tool_output(summary)

    def live_incremental_response(self, final):
        show_resp = self.render_incremental_response(final)

        # Also update the live delegate if it exists (for background prompt support)
        if self.live_delegate:
            # Get just the new content since last update
            if not hasattr(self, "_last_notified_content"):
                self._last_notified_content = ""

            new_content = show_resp[len(self._last_notified_content):]
            if new_content:
                # Pass thinking status if we are in a reasoning block
                got_reasoning = getattr(self, "got_reasoning_content", False)
                ended_reasoning = getattr(self, "ended_reasoning_content", False)
                is_thinking = got_reasoning and not ended_reasoning
                self.live_delegate.append_content(new_content, is_thinking=is_thinking)
                self._last_notified_content = show_resp

            if final:
                delattr(self, "_last_notified_content")

        show_resp = replace_reasoning_tags(show_resp, self.reasoning_tag_name)
        self.mdstream.update(show_resp, final=final)

    def render_incremental_response(self, final):
        return self.get_multi_response_content_in_progress()

    def remove_reasoning_content(self):
        """Remove reasoning content from the model's response."""
        self.partial_response_content = remove_reasoning_content(
            self.partial_response_content,
            self.reasoning_tag_name,
        )

    def calculate_and_show_tokens_and_cost(self, messages, completion=None):
        prompt_tokens = 0
        completion_tokens = 0
        cache_hit_tokens = 0
        cache_write_tokens = 0

        if completion and hasattr(completion, "usage") and completion.usage is not None:
            prompt_tokens = completion.usage.prompt_tokens
            completion_tokens = completion.usage.completion_tokens
            cache_hit_tokens = getattr(completion.usage, "prompt_cache_hit_tokens", 0) or getattr(
                completion.usage, "cache_read_input_tokens", 0
            )
            cache_write_tokens = getattr(completion.usage, "cache_creation_input_tokens", 0)

            # Track cache statistics for session summary
            self.total_cache_hit_tokens += cache_hit_tokens
            self.total_cache_write_tokens += cache_write_tokens
            # Uncached tokens = prompt tokens minus cache hits (if API includes cached in prompt_tokens)
            # Some APIs include cache hits in prompt_tokens, others don't
            uncached = prompt_tokens - cache_hit_tokens if cache_hit_tokens <= prompt_tokens else prompt_tokens
            self.total_uncached_input_tokens += uncached

            if hasattr(completion.usage, "cache_read_input_tokens") or hasattr(
                completion.usage, "cache_creation_input_tokens"
            ):
                self.message_tokens_sent += prompt_tokens
                self.message_tokens_sent += cache_write_tokens
            else:
                self.message_tokens_sent += prompt_tokens

        else:
            prompt_tokens = self.main_model.token_count(messages)
            completion_tokens = self.main_model.token_count(self.partial_response_content)
            self.message_tokens_sent += prompt_tokens

        self.message_tokens_received += completion_tokens

        tokens_report = f"Tokens: {format_tokens(self.message_tokens_sent)} sent"

        if cache_write_tokens:
            tokens_report += f", {format_tokens(cache_write_tokens)} cache write"
        if cache_hit_tokens:
            tokens_report += f", {format_tokens(cache_hit_tokens)} cache hit"
        tokens_report += f", {format_tokens(self.message_tokens_received)} received."

        if not self.main_model.info.get("input_cost_per_token"):
            self.usage_report = tokens_report
            return

        try:
            cost = litellm.completion_cost(completion_response=completion)
        except Exception:
            cost = 0

        if not cost:
            cost = self.compute_costs_from_tokens(
                prompt_tokens, completion_tokens, cache_write_tokens, cache_hit_tokens
            )

        self.total_cost += cost
        self.message_cost += cost

        def format_cost(value):
            if value == 0:
                return "0.00"
            magnitude = abs(value)
            if magnitude >= 0.01:
                return f"{value:.2f}"
            else:
                return f"{value:.{max(2, 2 - int(math.log10(magnitude)))}f}"

        cost_report = (
            f"Cost: ${format_cost(self.message_cost)} message,"
            f" ${format_cost(self.total_cost)} session."
        )

        sep = "\n" if cache_hit_tokens and cache_write_tokens else " "
        self.usage_report = tokens_report + sep + cost_report

    def compute_costs_from_tokens(
        self, prompt_tokens, completion_tokens, cache_write_tokens, cache_hit_tokens
    ):
        cost = 0

        input_cost_per_token = self.main_model.info.get("input_cost_per_token") or 0
        output_cost_per_token = self.main_model.info.get("output_cost_per_token") or 0
        input_cost_per_token_cache_hit = (
            self.main_model.info.get("input_cost_per_token_cache_hit") or 0
        )

        if input_cost_per_token_cache_hit:
            cost += input_cost_per_token_cache_hit * cache_hit_tokens
            cost += (prompt_tokens - input_cost_per_token_cache_hit) * input_cost_per_token
        else:
            cost += cache_write_tokens * input_cost_per_token * 1.25
            cost += cache_hit_tokens * input_cost_per_token * 0.10
            cost += prompt_tokens * input_cost_per_token

        cost += completion_tokens * output_cost_per_token
        return cost

    def show_usage_report(self):
        if not self.usage_report:
            return

        self.total_tokens_sent += self.message_tokens_sent
        self.total_tokens_received += self.message_tokens_received

        self.io.tool_output(self.usage_report)

        prompt_tokens = self.message_tokens_sent
        completion_tokens = self.message_tokens_received
        self.event(
            "message_send",
            main_model=self.main_model,
            edit_format=self.edit_format,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost=self.message_cost,
            total_cost=self.total_cost,
        )

        self.message_cost = 0.0
        self.message_tokens_sent = 0
        self.message_tokens_received = 0

    def reset_token_cache_stats(self):
        """Reset token cache statistics. Useful for testing or new sessions."""
        self.total_cache_hit_tokens = 0
        self.total_cache_write_tokens = 0
        self.total_uncached_input_tokens = 0

    def get_multi_response_content_in_progress(self, final=False):
        cur = self.multi_response_content or ""
        new = self.partial_response_content or ""

        if new.rstrip() != new and not final:
            new = new.rstrip()

        return cur + new
