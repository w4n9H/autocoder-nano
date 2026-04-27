BUILTIN_MODELS = {
    "(DeepSeek)deepseek/deepseek-v4-flash": {
        "id": "1",
        "base_url": "https://api.deepseek.com",
        "model_name": "deepseek-v4-flash",
        "description": "引入全新注意力机制，结合DSA稀疏注意力，Agent能力强化，百万上下文",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 1_000_000
    },
    "(DeepSeek)deepseek/deepseek-v4-pro": {
        "id": "2",
        "base_url": "https://api.deepseek.com",
        "model_name": "deepseek-v4-pro",
        "description": "引入全新注意力机制，结合DSA稀疏注意力，Agent能力强化，百万上下文",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 1_000_000
    },
    "(BigModel)bigmodel/glm-5.1": {
        "id": "3",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model_name": "glm-5.1",
        "description": "通用能力强，适合多轮对话",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 200_000
    },
    "(BigModel)bigmodel/glm-5v-turbo": {
        "id": "4",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model_name": "glm-5v-turbo",
        "description": "通用能力强，适合多轮对话",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 200_000
    },
    "(BigModel)bigmodel/token-plan": {
        "id": "5",
        "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
        "model_name": "glm-5.1",
        "description": "编码能力强，适合多轮对话",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 200_000
    },
    "(MiniMax)minimax/minimax-m2.7": {
        "id": "6",
        "base_url": "https://api.minimaxi.com/v1",
        "model_name": "MiniMax-M2.7",
        "description": "编码能力强，适合多轮对话",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 204_800
    },
    "(MiniMax)minimax/token-plan": {
        "id": "7",
        "base_url": "https://api.minimaxi.com/v1",
        "model_name": "MiniMax-M2.7",
        "description": "专攻编程",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 204_800
    },
    "(MoonShot)kimi/kimi-2.6": {
        "id": "8",
        "base_url": "https://api.moonshot.cn/v1",
        "model_name": "kimi-k2.6",
        "description": "专攻编程",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 256_000
    },
    "(MoonShot)kimi/token-plan": {
        "id": "9",
        "base_url": "https://api.kimi.com/coding/v1",
        "model_name": "kimi-for-coding",
        "description": "专攻编程",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 256_000
    },
    "(OpenRouter)anthropic/claude-opus-4.7": {
        "id": "10",
        "base_url": "https://openrouter.ai/api/v1",
        "model_name": "anthropic/claude-opus-4.7",
        "description": "擅长深度编程与复杂工作流",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 1_000_000
    },
    "(OpenRouter)anthropic/claude-sonnet-4.5": {
        "id": "11",
        "base_url": "https://openrouter.ai/api/v1",
        "model_name": "anthropic/claude-sonnet-4.5",
        "description": "均衡性能，适合企业级自动化",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 1_000_000
    },
    "(OpenRouter)openai/gpt-5.4": {
        "id": "12",
        "base_url": "https://openrouter.ai/api/v1",
        "model_name": "openai/gpt-5.4",
        "description": "全能型模型，综合能力领先",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 1_000_000
    }
}


def get_model_max_context(model_name: str) -> int:
    if model_name not in BUILTIN_MODELS:
        return 0
    return BUILTIN_MODELS[model_name]["context"]