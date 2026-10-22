"""Authentication flows for various provider types.

Each flow is a self-contained class with a single ``run()`` method that
performs the interactive authentication and returns the obtained credential.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger(__name__)


class AuthFlow(ABC):
    """Abstract base for all auth flows."""

    @abstractmethod
    def run(self) -> str:
        """Execute the flow and return the obtained credential value."""


# ---------------------------------------------------------------------------
# ApiKeyFlow — 直接提示用户输入并保存 API Key
# ---------------------------------------------------------------------------


class ApiKeyFlow(AuthFlow):
    """Prompt the user for an API key and persist it via :mod:`questorharness.auth.storage`."""

    def __init__(self, provider: str, prompt_text: str | None = None) -> None:
        self.provider = provider
        self.prompt_text = prompt_text or f"Enter your {provider} API key"

    def run(self) -> str:
        import getpass

        key = getpass.getpass(f"{self.prompt_text}: ").strip()
        if not key:
            raise ValueError("API key cannot be empty.")
        return key


# ---------------------------------------------------------------------------
# DeviceCodeFlow — GitHub OAuth 设备码流程（从 copilot_auth 重构）
# ---------------------------------------------------------------------------


class DeviceCodeFlow(AuthFlow):
    """GitHub OAuth device-code flow.

    This is a refactored version of the logic previously inlined in
    ``cli.py`` (``auth_copilot_login``).  It can be used for any GitHub
    OAuth app that supports the device-code grant.
    """

    def __init__(
        self,
        client_id: str | None = None,
        github_domain: str = "github.com",
        enterprise_url: str | None = None,
        *,
        progress_callback: Any | None = None,
    ) -> None:
        from questorharness.api.copilot_auth import COPILOT_CLIENT_ID

        self.client_id = client_id or COPILOT_CLIENT_ID
        self.enterprise_url = enterprise_url
        self.github_domain = github_domain if not enterprise_url else enterprise_url
        self.progress_callback = progress_callback

    @staticmethod
    def _try_open_browser(url: str) -> bool:
        """Attempt to open *url* in the default browser; return True if likely succeeded."""
        # 此处仅允许 http(s) URL。ShellExecute / xdg-open / `open`
        # 都会把无法识别的协议（例如 ``file:``、``javascript:``、
        # 裸可执行文件名）按注册表或 PATH 解析，因此拒绝
        # 其他所有形式可消除一类误触发操作的风险。
        if urlparse(url).scheme not in {"http", "https"}:
            return False
        try:
            plat = platform.system()
            if plat == "Darwin":
                subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            if plat == "Windows":
                # 通过 os.startfile 调用 ShellExecute — 不会经过
                # cmd.exe，因此 URL 中的 ``&`` / ``|`` / ``^`` 不会被
                # 解释为命令分隔符。这替代了此前
                # ``subprocess.Popen([...], shell=True)`` 的写法，该写法会
                # 在设备码端点被攻击或劫持并返回
                # 类似以下 URL 时执行附加命令：
                # ``https://x.com&calc.exe``。
                os.startfile(url)  # type: ignore[attr-defined]
                return True
            # Linux / WSL
            proc = subprocess.Popen(
                ["xdg-open", url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                proc.wait(timeout=2)
                return proc.returncode == 0
            except subprocess.TimeoutExpired:
                return True
        except Exception:
            return False
        return False

    def run(self) -> str:
        from questorharness.api.copilot_auth import poll_for_access_token, request_device_code

        print("Starting GitHub device flow...", flush=True)
        dc = request_device_code(client_id=self.client_id, github_domain=self.github_domain)

        print(flush=True)
        print(f"  Open: {dc.verification_uri}", flush=True)
        print(f"  Code: {dc.user_code}", flush=True)
        print(flush=True)

        opened = self._try_open_browser(dc.verification_uri)
        if opened:
            print("(Browser opened — enter the code shown above.)", flush=True)
        else:
            print("Open the URL above in your browser and enter the code.", flush=True)
        print(flush=True)

        if self.progress_callback is None:

            def _default_progress(poll_num: int, elapsed: float) -> None:
                mins = int(elapsed) // 60
                secs = int(elapsed) % 60
                print(f"\r  Polling... ({mins}m {secs:02d}s elapsed)", end="", flush=True)

            self.progress_callback = _default_progress

        print("Waiting for authorisation...", flush=True)
        try:
            token = poll_for_access_token(
                dc.device_code,
                dc.interval,
                client_id=self.client_id,
                github_domain=self.github_domain,
                progress_callback=self.progress_callback,
            )
        except RuntimeError as exc:
            print(flush=True)
            print(f"Error: {exc}", file=sys.stderr, flush=True)
            raise

        print(flush=True)
        return token


# ---------------------------------------------------------------------------
# BrowserFlow — 打开 URL 并等待用户完成认证
# ---------------------------------------------------------------------------


class BrowserFlow(AuthFlow):
    """Open a browser URL and wait for the user to complete authentication.

    After the user completes the browser flow they are expected to paste
    back a token/code — this simple implementation prompts for that value.
    """

    def __init__(self, auth_url: str, prompt_text: str = "Paste the token from your browser") -> None:
        self.auth_url = auth_url
        self.prompt_text = prompt_text

    def run(self) -> str:
        import getpass

        print(f"Opening browser for authentication: {self.auth_url}", flush=True)
        opened = DeviceCodeFlow._try_open_browser(self.auth_url)
        if not opened:
            print(f"Could not open browser automatically. Visit: {self.auth_url}", flush=True)

        token = getpass.getpass(f"{self.prompt_text}: ").strip()
        if not token:
            raise ValueError("No token provided.")
        return token
