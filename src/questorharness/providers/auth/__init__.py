"""Unified authentication management for QuestorHarness."""

from questorharness.providers.auth.flows import ApiKeyFlow, BrowserFlow, DeviceCodeFlow
from questorharness.providers.auth.auth_manager import AuthManager
from questorharness.providers.auth.storage import (
    clear_provider_credentials,
    decrypt,
    encrypt,
    load_credential,
    load_external_binding,
    store_credential,
    store_external_binding,
)

__all__ = [
    "AuthManager",
    "ApiKeyFlow",
    "BrowserFlow",
    "DeviceCodeFlow",
    "store_credential",
    "load_credential",
    "store_external_binding",
    "load_external_binding",
    "clear_provider_credentials",
    # 已弃用 — 如需使用请直接调用 _obfuscate/_deobfuscate。
    # 保留用于向后兼容，将在未来版本中移除。
    "encrypt",
    "decrypt",
]

