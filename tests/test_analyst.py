import analyst
import scanner


class FakeToolUseBlock:
    def __init__(self, input_data):
        self.type = "tool_use"
        self.input = input_data


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeMessages:
    def __init__(self, decision_input):
        self._decision_input = decision_input
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return FakeResponse([FakeToolUseBlock(self._decision_input)])


class FakeClient:
    def __init__(self, decision_input):
        self.messages = FakeMessages(decision_input)


def test_build_prompt_includes_key_market_facts():
    market = scanner.Market("0x1", "Will X happen?", 0.42, 15000.0, 0.30, "resolves on NOAA data")
    prompt = analyst.build_prompt(market, mispricing_pct=40.0)

    assert "Will X happen?" in prompt
    assert "resolves on NOAA data" in prompt
    assert "40.0%" in prompt


def test_analyze_market_parses_structured_decision():
    market = scanner.Market("0x1", "Will X happen?", 0.42, 15000.0, 0.30, "resolves on NOAA data")
    client = FakeClient({
        "trade": True, "direction": "yes", "confidence": 0.8, "rationale": "clear edge",
    })

    decision = analyst.analyze_market(client, market, mispricing_pct=40.0)

    assert decision.market_id == "0x1"
    assert decision.trade is True
    assert decision.direction == "yes"
    assert decision.confidence == 0.8
    assert decision.rationale == "clear edge"
    assert client.messages.last_kwargs["tool_choice"] == {"type": "tool", "name": "record_decision"}
