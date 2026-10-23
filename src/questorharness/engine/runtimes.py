"""Provider runtime singletons injected into tool execution contexts."""

from __future__ import annotations

from questorharness.providers.llm.tool_runtime import ProviderLlmToolRuntime
from questorharness.providers.lsp.runtime import ProviderLspRuntime
from questorharness.providers.sandbox.runtime import ProviderSandboxRuntime

TOOL_SANDBOX_RUNTIME = ProviderSandboxRuntime()
TOOL_LLM_RUNTIME = ProviderLlmToolRuntime()
TOOL_LSP_RUNTIME = ProviderLspRuntime()
