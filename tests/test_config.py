from config import load_config


def test_load_config_reads_yaml_and_env(tmp_path, monkeypatch):
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "mispricing_threshold_pct: 8.0\n"
        "shortlist_size: 8\n"
        "kelly_cap_pct: 6.0\n"
        "floor_usd: 50.0\n"
        "ceiling_usd: 75.0\n"
        "stop_loss_pct: 25.0\n"
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        "ANTHROPIC_API_KEY=test-key\n"
        "TELEGRAM_BOT_TOKEN=test-token\n"
        "TELEGRAM_CHAT_ID=12345\n"
    )
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    config = load_config(str(yaml_path), str(env_path))

    assert config.mispricing_threshold_pct == 8.0
    assert config.shortlist_size == 8
    assert config.kelly_cap_pct == 6.0
    assert config.floor_usd == 50.0
    assert config.ceiling_usd == 75.0
    assert config.stop_loss_pct == 25.0
    assert config.anthropic_api_key == "test-key"
    assert config.telegram_bot_token == "test-token"
    assert config.telegram_chat_id == "12345"


def test_load_config_defaults_telegram_to_empty_when_not_set(tmp_path, monkeypatch):
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "mispricing_threshold_pct: 8.0\n"
        "shortlist_size: 8\n"
        "kelly_cap_pct: 6.0\n"
        "floor_usd: 50.0\n"
        "ceiling_usd: 75.0\n"
        "stop_loss_pct: 25.0\n"
    )
    env_path = tmp_path / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=test-key\n")  # no Telegram vars at all
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    config = load_config(str(yaml_path), str(env_path))

    assert config.anthropic_api_key == "test-key"
    assert config.telegram_bot_token == ""
    assert config.telegram_chat_id == ""
