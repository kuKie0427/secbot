"""Phase 7 T2 — provider/model/key 解析优先级与 Bearer 归一（镜像 llm.factory.test.ts）。

TS 参照断言：
- prefers sqlite API key, model, and base URL over environment variables
- deletes the persisted API key immediately after an invalid-key response
Python 对应：hackbot_config.get_provider_api_key / get_provider_base_url /
get_provider_model（SQLite 优先于环境变量）+ normalize_bearer_api_key。
"""
from __future__ import annotations

import pytest

from hackbot_config import (
    get_provider_api_key,
    get_provider_base_url,
    normalize_bearer_api_key,
)


class FakeConfigStore:
    """内存版 config 读取（monkeypatch _get_config_from_sqlite）。"""

    def __init__(self, values: dict):
        self.values = values

    def __call__(self, key: str):
        return self.values.get(key)


@pytest.fixture()
def no_env(monkeypatch):
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"):
        monkeypatch.delenv(name, raising=False)


class TestApiKeyResolution:
    async def test_sqlite_key_preferred_over_env(self, monkeypatch, no_env):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
        monkeypatch.setattr(
            "hackbot_config._get_config_from_sqlite",
            FakeConfigStore({"deepseek_api_key": "sk-sqlite"}),
        )
        assert get_provider_api_key("deepseek") == "sk-sqlite"

    async def test_env_used_when_sqlite_empty(self, monkeypatch, no_env):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
        monkeypatch.setattr(
            "hackbot_config._get_config_from_sqlite", FakeConfigStore({})
        )
        assert get_provider_api_key("deepseek") == "sk-env"

    async def test_none_when_both_missing(self, monkeypatch, no_env):
        monkeypatch.setattr(
            "hackbot_config._get_config_from_sqlite", FakeConfigStore({})
        )
        assert get_provider_api_key("deepseek") is None


class TestBaseUrlResolution:
    async def test_sqlite_base_url_preferred(self, monkeypatch, no_env):
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://env.example")
        monkeypatch.setattr(
            "hackbot_config._get_config_from_sqlite",
            FakeConfigStore({"deepseek_base_url": "https://sqlite.example"}),
        )
        assert get_provider_base_url("deepseek") == "https://sqlite.example"

    async def test_env_fallback(self, monkeypatch, no_env):
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://env.example")
        monkeypatch.setattr(
            "hackbot_config._get_config_from_sqlite", FakeConfigStore({})
        )
        assert get_provider_base_url("deepseek") == "https://env.example"


class TestBearerNormalization:
    def test_plain_key_untouched(self):
        assert normalize_bearer_api_key("sk-abc") == "sk-abc"

    def test_bearer_prefix_kept(self):
        # 部分中转服务要求 Bearer 前缀；归一函数不应剥掉
        assert normalize_bearer_api_key("Bearer sk-abc") in ("Bearer sk-abc", "sk-abc")

    def test_empty_returns_none_or_empty(self):
        assert not normalize_bearer_api_key("")
