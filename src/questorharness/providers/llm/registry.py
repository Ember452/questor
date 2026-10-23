"""
LLM Provider Registry — single source of truth for provider metadata.

Adding a new provider:
  1. Add a ProviderSpec to PROVIDERS below.
  Done. Detection, display, and config all derive from here.

Order matters — it controls match priority. Gateways and cloud providers first,
standard providers by keyword, local/special providers last.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    """One LLM provider's metadata.

    backend_type:
      "anthropic"    — Anthropic SDK (default for claude-* models)
      "openai_compat" — OpenAI-compatible REST API
      "copilot"      — GitHub Copilot OAuth flow
    """

    # 标识
    name: str  # 规范名称，例如 "dashscope"
    keywords: tuple[str, ...]  # 用于检测的模型名子串（小写）
    env_key: str  # 主 API Key 环境变量
    display_name: str = ""  # 在状态/诊断信息中展示

    # 路由
    backend_type: str = "openai_compat"  # "anthropic" | "openai_compat" | "copilot"
    default_base_url: str = ""  # 此提供商的回退基础 URL

    # 自动检测信号
    detect_by_key_prefix: str = ""  # 匹配 api_key 前缀，例如 "sk-or-"
    detect_by_base_keyword: str = ""  # 匹配 base_url 中的子串

    # 分类标志
    is_gateway: bool = False  # 可路由任意模型（OpenRouter、AiHubMix 等）
    is_local: bool = False  # 本地部署（vLLM、Ollama）
    is_oauth: bool = False  # 使用 OAuth 而非 API Key

    @property
    def label(self) -> str:
        return self.display_name or self.name.title()


# ---------------------------------------------------------------------------
# PROVIDERS 注册表 — 顺序即检测优先级。
# ---------------------------------------------------------------------------

PROVIDERS: tuple[ProviderSpec, ...] = (
    # === GitHub Copilot（OAuth，通过 api_format="copilot" 检测） ============
    ProviderSpec(
        name="github_copilot",
        keywords=("copilot",),
        env_key="",
        display_name="GitHub Copilot",
        backend_type="copilot",
        default_base_url="",
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        is_gateway=False,
        is_local=False,
        is_oauth=True,
    ),
    # === 网关（通过 api_key 前缀 / base_url 关键字检测） ============
    # OpenRouter：全球网关，密钥以 "sk-or-" 开头
    ProviderSpec(
        name="openrouter",
        keywords=("openrouter",),
        env_key="OPENROUTER_API_KEY",
        display_name="OpenRouter",
        backend_type="openai_compat",
        default_base_url="https://openrouter.ai/api/v1",
        detect_by_key_prefix="sk-or-",
        detect_by_base_keyword="openrouter",
        is_gateway=True,
        is_local=False,
        is_oauth=False,
    ),
    # AiHubMix：OpenAI 兼容网关
    ProviderSpec(
        name="aihubmix",
        keywords=("aihubmix",),
        env_key="OPENAI_API_KEY",
        display_name="AiHubMix",
        backend_type="openai_compat",
        default_base_url="https://aihubmix.com/v1",
        detect_by_key_prefix="",
        detect_by_base_keyword="aihubmix",
        is_gateway=True,
        is_local=False,
        is_oauth=False,
    ),
    # SiliconFlow（硅基流动）：OpenAI 兼容网关
    ProviderSpec(
        name="siliconflow",
        keywords=("siliconflow",),
        env_key="OPENAI_API_KEY",
        display_name="SiliconFlow",
        backend_type="openai_compat",
        default_base_url="https://api.siliconflow.cn/v1",
        detect_by_key_prefix="",
        detect_by_base_keyword="siliconflow",
        is_gateway=True,
        is_local=False,
        is_oauth=False,
    ),
    # VolcEngine（火山引擎 / Ark）：OpenAI 兼容网关
    ProviderSpec(
        name="volcengine",
        keywords=("volcengine", "volces", "ark"),
        env_key="OPENAI_API_KEY",
        display_name="VolcEngine",
        backend_type="openai_compat",
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        detect_by_key_prefix="",
        detect_by_base_keyword="volces",
        is_gateway=True,
        is_local=False,
        is_oauth=False,
    ),
    # ModelScope：OpenAI 兼容推理 API
    ProviderSpec(
        name="modelscope",
        keywords=("modelscope",),
        env_key="MODELSCOPE_API_KEY",
        display_name="ModelScope",
        backend_type="openai_compat",
        default_base_url="https://api-inference.modelscope.cn/v1",
        detect_by_key_prefix="",
        detect_by_base_keyword="modelscope",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # === 标准云提供商（通过模型名关键字匹配） ============
    # Anthropic：claude-* 模型使用原生 SDK
    ProviderSpec(
        name="anthropic",
        keywords=("anthropic", "claude"),
        env_key="ANTHROPIC_API_KEY",
        display_name="Anthropic",
        backend_type="anthropic",
        default_base_url="",
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # OpenAI：gpt-* 模型
    ProviderSpec(
        name="openai",
        keywords=("openai", "gpt", "o1", "o3", "o4"),
        env_key="OPENAI_API_KEY",
        display_name="OpenAI",
        backend_type="openai_compat",
        default_base_url="",
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # DeepSeek
    ProviderSpec(
        name="deepseek",
        keywords=("deepseek",),
        env_key="DEEPSEEK_API_KEY",
        display_name="DeepSeek",
        backend_type="openai_compat",
        default_base_url="https://api.deepseek.com/v1",
        detect_by_key_prefix="",
        detect_by_base_keyword="deepseek",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # Google Gemini
    ProviderSpec(
        name="gemini",
        keywords=("gemini",),
        env_key="GEMINI_API_KEY",
        display_name="Gemini",
        backend_type="openai_compat",
        default_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        detect_by_key_prefix="",
        detect_by_base_keyword="googleapis",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # DashScope（Qwen / 阿里云）
    ProviderSpec(
        name="dashscope",
        keywords=("qwen", "dashscope"),
        env_key="DASHSCOPE_API_KEY",
        display_name="DashScope",
        backend_type="openai_compat",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        detect_by_key_prefix="",
        detect_by_base_keyword="dashscope",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # Moonshot / Kimi
    ProviderSpec(
        name="moonshot",
        keywords=("moonshot", "kimi"),
        env_key="MOONSHOT_API_KEY",
        display_name="Moonshot",
        backend_type="openai_compat",
        default_base_url="https://api.moonshot.ai/v1",
        detect_by_key_prefix="",
        detect_by_base_keyword="moonshot",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # MiniMax
    ProviderSpec(
        name="minimax",
        keywords=("minimax",),
        env_key="MINIMAX_API_KEY",
        display_name="MiniMax",
        backend_type="openai_compat",
        default_base_url="https://api.minimax.io/v1",
        detect_by_key_prefix="",
        detect_by_base_keyword="minimax",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # 智谱 AI / GLM
    ProviderSpec(
        name="zhipu",
        keywords=("zhipu", "glm", "chatglm"),
        env_key="ZHIPUAI_API_KEY",
        display_name="Zhipu AI",
        backend_type="openai_compat",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        detect_by_key_prefix="",
        detect_by_base_keyword="bigmodel",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # Groq
    ProviderSpec(
        name="groq",
        keywords=("groq",),
        env_key="GROQ_API_KEY",
        display_name="Groq",
        backend_type="openai_compat",
        default_base_url="https://api.groq.com/openai/v1",
        detect_by_key_prefix="gsk_",
        detect_by_base_keyword="groq",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # Mistral
    ProviderSpec(
        name="mistral",
        keywords=("mistral", "mixtral", "codestral"),
        env_key="MISTRAL_API_KEY",
        display_name="Mistral",
        backend_type="openai_compat",
        default_base_url="https://api.mistral.ai/v1",
        detect_by_key_prefix="",
        detect_by_base_keyword="mistral",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # StepFun（阶跃星辰）
    ProviderSpec(
        name="stepfun",
        keywords=("step-", "stepfun"),
        env_key="STEPFUN_API_KEY",
        display_name="StepFun",
        backend_type="openai_compat",
        default_base_url="https://api.stepfun.com/v1",
        detect_by_key_prefix="",
        detect_by_base_keyword="stepfun",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # 百度 / ERNIE
    ProviderSpec(
        name="baidu",
        keywords=("ernie", "baidu"),
        env_key="QIANFAN_ACCESS_KEY",
        display_name="Baidu",
        backend_type="openai_compat",
        default_base_url="https://qianfan.baidubce.com/v2",
        detect_by_key_prefix="",
        detect_by_base_keyword="baidubce",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # === 云平台提供商（通过 base_url 检测） ====================
    # AWS Bedrock
    ProviderSpec(
        name="bedrock",
        keywords=("bedrock",),
        env_key="AWS_ACCESS_KEY_ID",
        display_name="AWS Bedrock",
        backend_type="openai_compat",
        default_base_url="",
        detect_by_key_prefix="",
        detect_by_base_keyword="bedrock",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # Google Vertex AI
    ProviderSpec(
        name="vertex",
        keywords=("vertex",),
        env_key="GOOGLE_APPLICATION_CREDENTIALS",
        display_name="Vertex AI",
        backend_type="openai_compat",
        default_base_url="",
        detect_by_key_prefix="",
        detect_by_base_keyword="aiplatform",
        is_gateway=False,
        is_local=False,
        is_oauth=False,
    ),
    # === 本地部署（通过关键字或 base_url 匹配） =================
    # Ollama
    ProviderSpec(
        name="ollama",
        keywords=("ollama",),
        env_key="",
        display_name="Ollama",
        backend_type="openai_compat",
        default_base_url="http://localhost:11434/v1",
        detect_by_key_prefix="",
        detect_by_base_keyword="localhost:11434",
        is_gateway=False,
        is_local=True,
        is_oauth=False,
    ),
    # vLLM / 任意 OpenAI 兼容本地服务器
    ProviderSpec(
        name="vllm",
        keywords=("vllm",),
        env_key="",
        display_name="vLLM/Local",
        backend_type="openai_compat",
        default_base_url="",
        detect_by_key_prefix="",
        detect_by_base_keyword="",
        is_gateway=False,
        is_local=True,
        is_oauth=False,
    ),
)


# ---------------------------------------------------------------------------
# 查找辅助函数
# ---------------------------------------------------------------------------


def find_by_name(name: str) -> ProviderSpec | None:
    """Find a provider spec by canonical name, e.g. "dashscope"."""
    for spec in PROVIDERS:
        if spec.name == name:
            return spec
    return None


def _match_by_model(model: str) -> ProviderSpec | None:
    """Match a standard/gateway provider by model-name keyword (case-insensitive)."""
    model_lower = model.lower()
    model_normalized = model_lower.replace("-", "_")
    model_prefix = model_lower.split("/", 1)[0] if "/" in model_lower else ""
    normalized_prefix = model_prefix.replace("-", "_")

    std_specs = [s for s in PROVIDERS if not s.is_local and not s.is_oauth]

    # 优先匹配显式提供商前缀（例如 "deepseek/..." → deepseek 配置）
    for spec in std_specs:
        if model_prefix and normalized_prefix == spec.name:
            return spec

    # 回退到关键字扫描
    for spec in std_specs:
        if any(
            kw in model_lower or kw.replace("-", "_") in model_normalized
            for kw in spec.keywords
        ):
            return spec
    return None


def detect_provider_from_registry(
    model: str,
    api_key: str | None = None,
    base_url: str | None = None,
) -> ProviderSpec | None:
    """Detect the best-matching ProviderSpec for the given inputs.

    Detection priority:
      1. api_key prefix  (e.g. "sk-or-" → OpenRouter)
      2. base_url keyword (e.g. "aihubmix" in URL → AiHubMix)
      3. model name keyword (e.g. "qwen" → DashScope)
    """
    # 1. api_key 前缀
    if api_key:
        for spec in PROVIDERS:
            if spec.detect_by_key_prefix and api_key.startswith(spec.detect_by_key_prefix):
                return spec

    # 2. base_url 关键字
    if base_url:
        base_lower = base_url.lower()
        for spec in PROVIDERS:
            if spec.detect_by_base_keyword and spec.detect_by_base_keyword in base_lower:
                return spec

    # 3. 模型关键字
    if model:
        return _match_by_model(model)

    return None
