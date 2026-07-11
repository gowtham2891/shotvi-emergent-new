"""
ClipForge — Token & Cost Tracker
=================================
Drop-in module for tracking Gemini API token usage and cost
across pipeline runs.

Usage:
    from token_tracker import TokenTracker

    tracker = TokenTracker(model="gemini-3-flash-preview")

    # After every Gemini response:
    tracker.record(response, agent_name="Scout", call_type="text")

    # At the end of the pipeline:
    tracker.print_summary()
    report = tracker.get_report()   # dict you can save to JSON

MODELS SUPPORTED:
    "gemini-3-flash-preview"              — $0.50 input / $3.00 output
    "gemini-3.1-flash-lite"               — $0.10 input / $0.40 output
    "gemini-2.5-flash-preview-05-20"      — $0.30 input / $2.50 output
    "gemini-2.5-pro"                      — $1.25 input / $10.00 output
"""

import json
import time
from dataclasses import dataclass, field
from typing import Optional

# ── Pricing table (USD per 1M tokens) ────────────────────────────────────────
PRICING = {
    "gemini-3-flash-preview": {
        "input":        0.50,
        "output":       3.00,
        "cache_read":   0.05,
        "cache_write":  0.50,
        "cache_storage_per_hour": 1.00,
    },
    # PATCH 7: added flash-lite pricing
    "gemini-3.1-flash-lite": {
        "input":        0.10,
        "output":       0.40,
        "cache_read":   0.025,
        "cache_write":  0.10,
        "cache_storage_per_hour": 0.25,
    },
    "gemini-2.5-flash-preview-05-20": {
        "input":        0.30,
        "output":       2.50,
        "cache_read":   0.075,
        "cache_write":  0.30,
        "cache_storage_per_hour": 1.00,
    },
    "gemini-2.5-flash": {
        "input":        0.30,
        "output":       2.50,
        "cache_read":   0.075,
        "cache_write":  0.30,
        "cache_storage_per_hour": 1.00,
    },
    "gemini-2.5-pro": {
        "input":        1.25,
        "output":       10.00,
        "cache_read":   0.125,
        "cache_write":  1.25,
        "cache_storage_per_hour": 4.50,
    },
}

DEFAULT_PRICING = PRICING["gemini-3-flash-preview"]


@dataclass
class CallRecord:
    """One Gemini API call."""
    agent_name:      str
    call_type:       str
    input_tokens:    int   = 0
    output_tokens:   int   = 0
    thinking_tokens: int   = 0
    cached_tokens:   int   = 0
    input_cost:      float = 0.0
    output_cost:     float = 0.0
    cache_read_cost: float = 0.0
    total_cost:      float = 0.0
    timestamp:       float = field(default_factory=time.time)


class TokenTracker:
    """
    Tracks token usage and cost across an entire pipeline run.
    """

    def __init__(self, model: str = "gemini-3-flash-preview",
                 pipeline_name: str = "ClipForge"):
        self.model         = model
        self.pipeline_name = pipeline_name
        self.pricing       = PRICING.get(model, DEFAULT_PRICING)
        self.calls: list   = []
        self.start_time    = time.time()

        self._cache_tokens_stored = 0
        self._cache_ttl_seconds   = 0

    # ── Record a single Gemini response ──────────────────────────────────────

    def record(self, response, agent_name: str = "unknown",
               call_type: str = "text") -> CallRecord:
        """
        Extract token counts from a Gemini response object and record the call.
        """
        um = getattr(response, "usage_metadata", None)

        if um is not None:
            input_tokens    = getattr(um, "prompt_token_count",          0) or 0
            output_tokens   = getattr(um, "candidates_token_count",      0) or 0
            thinking_tokens = getattr(um, "thoughts_token_count",        0) or 0
            cached_tokens   = getattr(um, "cached_content_token_count",  0) or 0
        elif isinstance(response, dict):
            input_tokens    = response.get("prompt_token_count",         0) or 0
            output_tokens   = response.get("candidates_token_count",     0) or 0
            thinking_tokens = response.get("thoughts_token_count",       0) or 0
            cached_tokens   = response.get("cached_content_token_count", 0) or 0
        else:
            print(f"  [TokenTracker] ⚠ Unknown response type: {type(response)} — recording zeros")
            input_tokens = output_tokens = thinking_tokens = cached_tokens = 0

        billable_input  = input_tokens - cached_tokens
        billable_output = output_tokens

        p = self.pricing
        input_cost      = (billable_input  / 1_000_000) * p["input"]
        output_cost     = (billable_output / 1_000_000) * p["output"]
        cache_read_cost = (cached_tokens   / 1_000_000) * p["cache_read"]
        total_cost      = input_cost + output_cost + cache_read_cost

        rec = CallRecord(
            agent_name=agent_name,
            call_type=call_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
            cached_tokens=cached_tokens,
            input_cost=input_cost,
            output_cost=output_cost,
            cache_read_cost=cache_read_cost,
            total_cost=total_cost,
        )
        self.calls.append(rec)

        cache_str = f" | cached={cached_tokens:,}" if cached_tokens else ""
        think_str = f" | thinking={thinking_tokens:,}" if thinking_tokens else ""
        print(f"  [💰 {agent_name}] "
              f"in={input_tokens:,} out={output_tokens:,}{think_str}{cache_str} "
              f"→ ${total_cost:.4f}")

        return rec

    def track_cache_storage(self, tokens_stored: int, ttl_seconds: int) -> None:
        self._cache_tokens_stored = tokens_stored
        self._cache_ttl_seconds   = ttl_seconds
        hours = ttl_seconds / 3600
        storage_cost = (tokens_stored / 1_000_000) * self.pricing["cache_storage_per_hour"] * hours
        print(f"  [💾 Cache] Stored {tokens_stored:,} tokens for {ttl_seconds}s "
              f"→ storage cost ≈ ${storage_cost:.5f}")

    # ── Summary helpers ───────────────────────────────────────────────────────

    def _cache_storage_cost(self) -> float:
        if not self._cache_tokens_stored: return 0.0
        hours = self._cache_ttl_seconds / 3600
        return (self._cache_tokens_stored / 1_000_000) * self.pricing["cache_storage_per_hour"] * hours

    def total_tokens(self) -> dict:
        return {
            "input":    sum(c.input_tokens    for c in self.calls),
            "output":   sum(c.output_tokens   for c in self.calls),
            "thinking": sum(c.thinking_tokens for c in self.calls),
            "cached":   sum(c.cached_tokens   for c in self.calls),
        }

    def total_cost(self) -> float:
        return sum(c.total_cost for c in self.calls) + self._cache_storage_cost()

    def cost_by_agent(self) -> dict:
        result = {}
        for c in self.calls:
            if c.agent_name not in result:
                result[c.agent_name] = {"calls": 0, "total_cost": 0.0,
                                        "input_tokens": 0, "output_tokens": 0}
            result[c.agent_name]["calls"]         += 1
            result[c.agent_name]["total_cost"]    += c.total_cost
            result[c.agent_name]["input_tokens"]  += c.input_tokens
            result[c.agent_name]["output_tokens"] += c.output_tokens
        return result

    # ── Print summary ─────────────────────────────────────────────────────────

    def print_summary(self) -> None:
        elapsed  = time.time() - self.start_time
        totals   = self.total_tokens()
        by_agent = self.cost_by_agent()
        cache_storage = self._cache_storage_cost()

        print(f"\n{'═'*60}")
        print(f"  💰 TOKEN & COST SUMMARY — {self.pipeline_name}")
        print(f"  Model: {self.model}")
        print(f"  Elapsed: {elapsed:.1f}s  |  API calls: {len(self.calls)}")
        print(f"{'─'*60}")
        print(f"  {'AGENT':<28} {'CALLS':>5} {'INPUT':>10} {'OUTPUT':>10} {'COST':>10}")
        print(f"{'─'*60}")

        for agent, stats in sorted(by_agent.items(), key=lambda x: -x[1]["total_cost"]):
            print(f"  {agent:<28} {stats['calls']:>5} "
                  f"{stats['input_tokens']:>10,} {stats['output_tokens']:>10,} "
                  f"${stats['total_cost']:>9.4f}")

        print(f"{'─'*60}")
        total    = self.total_cost()
        api_cost = total - cache_storage
        print(f"  {'TOTAL API CALLS':<28} {len(self.calls):>5} "
              f"{totals['input']:>10,} {totals['output']:>10,} "
              f"${api_cost:>9.4f}")

        if cache_storage > 0:
            print(f"  {'CACHE STORAGE':<28} {'':>5} {'':>10} {'':>10} "
                  f"${cache_storage:>9.5f}")

        print(f"{'─'*60}")
        print(f"  {'GRAND TOTAL':<28} {'':>5} {'':>10} {'':>10} "
              f"${total:>9.4f}")
        print(f"{'─'*60}")

        cache_savings = 0.0
        for c in self.calls:
            if c.cached_tokens:
                savings = (c.cached_tokens / 1_000_000) * (
                    self.pricing["input"] - self.pricing["cache_read"])
                cache_savings += savings

        print(f"\n  Token breakdown:")
        print(f"    Input tokens    : {totals['input']:>12,}")
        print(f"    ├ Cached (cheap): {totals['cached']:>12,}  "
              f"(saved ${cache_savings:.4f} vs full price)")
        print(f"    ├ Non-cached    : {totals['input'] - totals['cached']:>12,}")
        print(f"    Output tokens   : {totals['output']:>12,}")
        if totals['thinking']:
            print(f"    ├ Thinking      : {totals['thinking']:>12,}  (billed as output)")
        print(f"{'═'*60}\n")

    # ── Export ────────────────────────────────────────────────────────────────

    def get_report(self) -> dict:
        totals   = self.total_tokens()
        by_agent = self.cost_by_agent()
        cache_s  = self._cache_storage_cost()
        elapsed  = time.time() - self.start_time

        return {
            "model":        self.model,
            "pipeline":     self.pipeline_name,
            "elapsed_sec":  round(elapsed, 1),
            "api_calls":    len(self.calls),
            "pricing_used": {
                "input_per_1m":      self.pricing["input"],
                "output_per_1m":     self.pricing["output"],
                "cache_read_per_1m": self.pricing["cache_read"],
            },
            "totals": {
                "input_tokens":           totals["input"],
                "output_tokens":          totals["output"],
                "thinking_tokens":        totals["thinking"],
                "cached_tokens":          totals["cached"],
                "api_cost_usd":           round(self.total_cost() - cache_s, 6),
                "cache_storage_cost_usd": round(cache_s, 6),
                "grand_total_usd":        round(self.total_cost(), 6),
            },
            "by_agent": {
                agent: {
                    "calls":         stats["calls"],
                    "input_tokens":  stats["input_tokens"],
                    "output_tokens": stats["output_tokens"],
                    "cost_usd":      round(stats["total_cost"], 6),
                }
                for agent, stats in by_agent.items()
            },
            "call_log": [
                {
                    "agent":           c.agent_name,
                    "type":            c.call_type,
                    "input_tokens":    c.input_tokens,
                    "output_tokens":   c.output_tokens,
                    "thinking_tokens": c.thinking_tokens,
                    "cached_tokens":   c.cached_tokens,
                    "cost_usd":        round(c.total_cost, 6),
                }
                for c in self.calls
            ],
        }