import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Config:
    mispricing_threshold_pct: float
    shortlist_size: int
    kelly_cap_pct: float
    floor_usd: float
    ceiling_usd: float
    stop_loss_pct: float
    anthropic_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str


def _load_env_file(env_path: str) -> None:
    path = Path(env_path)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def load_config(yaml_path: str = "config.yaml", env_path: str = ".env") -> Config:
    _load_env_file(env_path)

    with open(yaml_path) as f:
        raw = yaml.safe_load(f)

    return Config(
        mispricing_threshold_pct=raw["mispricing_threshold_pct"],
        shortlist_size=raw["shortlist_size"],
        kelly_cap_pct=raw["kelly_cap_pct"],
        floor_usd=raw["floor_usd"],
        ceiling_usd=raw["ceiling_usd"],
        stop_loss_pct=raw["stop_loss_pct"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
    )
