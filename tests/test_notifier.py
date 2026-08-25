import notifier


class FakeResponse:
    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, data=None, timeout=None):
        self.calls.append((url, data))
        return FakeResponse()


def test_send_message_posts_to_telegram_api():
    session = FakeSession()

    notifier.send_message("tok123", "chat456", "hello", session=session)

    assert len(session.calls) == 1
    url, data = session.calls[0]
    assert url == "https://api.telegram.org/bottok123/sendMessage"
    assert data == {"chat_id": "chat456", "text": "hello"}


def test_format_trade_alert_includes_key_numbers():
    text = notifier.format_trade_alert(
        question="Will X happen?", direction="yes", size_usd=3.0,
        confidence=0.8, equity_usd=52.0, floor_usd=50.0, ceiling_usd=75.0,
    )
    assert "Will X happen?" in text
    assert "YES" in text
    assert "$3.00" in text
    assert "80%" in text
    assert "$52.00" in text


def test_format_error_alert_includes_count_and_message():
    text = notifier.format_error_alert(error_count=3, last_error="timeout")
    assert "3" in text
    assert "timeout" in text
