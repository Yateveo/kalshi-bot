from dataclasses import dataclass

from scanner import Market

DECISION_TOOL = {
    "name": "record_decision",
    "description": "Record a trade decision for a prediction market.",
    "input_schema": {
        "type": "object",
        "properties": {
            "trade": {"type": "boolean", "description": "Whether to trade this market."},
            "direction": {"type": "string", "enum": ["yes", "no"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {
                "type": "string",
                "description": "One short sentence (under 20 words) explaining the decision. Output tokens cost more than input tokens -- be terse.",
            },
        },
        "required": ["trade", "direction", "confidence", "rationale"],
    },
}


@dataclass
class Decision:
    market_id: str
    trade: bool
    direction: str
    confidence: float
    rationale: str


RESOLUTION_CRITERIA_MAX_CHARS = 200


def build_prompt(market: Market, mispricing_pct: float) -> str:
    resolution_criteria = market.resolution_criteria[:RESOLUTION_CRITERIA_MAX_CHARS]
    return (
        f"Market: {market.question}\n"
        f"Resolution criteria: {resolution_criteria}\n"
        f"Current YES price: {market.yes_price}\n"
        f"Previous reference price: {market.price_reference}\n"
        f"24h volume: {market.volume_24h}\n"
        f"Computed mispricing score: {mispricing_pct:.1f}%\n\n"
        "Decide whether this mispricing is worth trading. Default toward "
        "trading when there's a plausible reason for the move and "
        "reasonable volume -- moderate uncertainty alone isn't a reason "
        "to pass. Only pass when there's essentially no real signal. "
        "Call record_decision with your answer."
    )


def analyze_market(client, market: Market, mispricing_pct: float) -> Decision:
    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=200,  # decision is 4 small fields + a capped one-sentence rationale
        tools=[DECISION_TOOL],
        tool_choice={"type": "tool", "name": "record_decision"},
        messages=[{"role": "user", "content": build_prompt(market, mispricing_pct)}],
    )
    tool_use_block = next(b for b in response.content if b.type == "tool_use")
    data = tool_use_block.input
    return Decision(
        market_id=market.market_id,
        trade=data["trade"],
        direction=data["direction"],
        confidence=data["confidence"],
        rationale=data["rationale"],
    )
