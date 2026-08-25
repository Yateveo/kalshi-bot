from dataclasses import dataclass


def kelly_fraction(confidence: float, cap_pct: float) -> float:
    """Kelly fraction for an even-money bet, capped at cap_pct of bankroll.

    Uses the simplified Kelly formula f* = 2p - 1 for an even-money
    outcome, floored at 0 (never size a bet against your own stated edge)
    and capped at cap_pct/100 regardless of how confident the edge is.
    """
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be in [0, 1], got {confidence}")
    if not 0.0 < cap_pct <= 100.0:
        raise ValueError(f"cap_pct must be in (0, 100], got {cap_pct}")
    raw = max(0.0, 2 * confidence - 1)
    return min(raw, cap_pct / 100.0)


@dataclass
class SizingResult:
    size_usd: float
    blocked_reason: str | None


def size_position(
    equity_usd: float, confidence: float, kelly_cap_pct: float,
    floor_usd: float, floor_reached: bool,
) -> SizingResult:
    """Size a new position using Kelly-capped equity, respecting the floor guard.

    floor_reached is a sticky latch, not a live comparison: it must mean
    "has equity ever reached floor_usd", and once True it must stay True
    forever for the life of the account, even if equity later dips back
    below floor_usd after a losing streak. Callers MUST compute and persist
    this as a monotonic value (e.g. a flag set once and never cleared) —
    NOT as a per-cycle check like `equity_usd >= floor_usd` recomputed fresh
    each call. A naive live comparison would let the floor guard silently
    switch off again whenever equity recovers above the floor and then
    drops back below it, defeating the floor guarantee this function exists
    to enforce.
    """
    fraction = kelly_fraction(confidence, kelly_cap_pct)
    proposed_size = equity_usd * fraction

    if floor_reached:
        headroom = equity_usd - floor_usd
        if headroom <= 0:
            return SizingResult(0.0, "at_or_below_floor")
        proposed_size = min(proposed_size, headroom)

    if proposed_size <= 0:
        return SizingResult(0.0, "zero_size")

    return SizingResult(proposed_size, None)


def apply_ceiling(
    equity_usd: float, reserved_usd: float, ceiling_usd: float, floor_usd: float,
) -> tuple[float, float]:
    """If equity is at/above the ceiling, sweep everything above the floor
    into the non-tradable reserved balance. Returns (tradable_equity, reserved_usd)."""
    if equity_usd < ceiling_usd:
        return (equity_usd, reserved_usd)
    # Clamp: if floor_usd > ceiling_usd (a misconfiguration config.py does not
    # validate), equity_usd - floor_usd can be negative. Never let a negative
    # sweep inflate tradable equity above actual equity or drive reserved_usd
    # negative.
    sweep = max(0.0, equity_usd - floor_usd)
    return (floor_usd, reserved_usd + sweep)


def should_stop_loss(entry_price: float, current_price: float, stop_loss_pct: float) -> bool:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    drop_pct = (entry_price - current_price) / entry_price * 100
    return drop_pct >= stop_loss_pct


def should_reverse_exit(original_confidence: float, new_confidence: float) -> bool:
    """Exit if confidence has flipped to the other side of a coin-flip (0.5)."""
    return (original_confidence >= 0.5) != (new_confidence >= 0.5)
