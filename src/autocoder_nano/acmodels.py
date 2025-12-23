BUILTIN_MODELS = {
    "(Volcengine)deepseek/deepseek-r1-0528": {
        "id": "1",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model_name": "deepseek-r1-250528",
        "description": "推理优化版，擅长深度思考与复杂推理",
        "input_price": 0.0,    # 单位:元/百万 input tokens
        "output_price": 0.0,  # 单位:元/百万 output tokens
        "context": 128000
    },
    "(Volcengine)deepseek/deepseek-v3.2": {
        "id": "2",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model_name": "deepseek-v3-2-251201",
        "description": "擅长数学求解与学术逻辑验证",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 128000
    },
    "(Volcengine)byte/doubao-seed-1.6-251015": {
        "id": "3",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model_name": "doubao-seed-1-6-251015",
        "description": "均衡型模型，适用日常任务",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 256000
    },
    "(Volcengine)moonshotai/kimi-k2": {
        "id": "4",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model_name": "kimi-k2-250905",
        "description": "擅长超长上下文信息处理",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 256000
    },
    "(iFlow)ali/qwen3-max": {
        "id": "5",
        "base_url": "https://apis.iflow.cn/v1",
        "model_name": "qwen3-max",
        "description": "擅长复杂编程与智能体任务",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 256000
    },
    "(iFlow)bigmodel/glm-4.7": {
        "id": "6",
        "base_url": "https://apis.iflow.cn/v1",
        "model_name": "glm-4.7",
        "description": "通用能力强，适合多轮对话",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 200000
    },
    "(OpenRouter)anthropic/claude-opus-4.5": {
        "id": "7",
        "base_url": "https://openrouter.ai/api/v1",
        "model_name": "anthropic/claude-opus-4.5",
        "description": "擅长深度编程与复杂工作流",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 200000
    },
    "(OpenRouter)anthropic/claude-sonnet-4.5": {
        "id": "8",
        "base_url": "https://openrouter.ai/api/v1",
        "model_name": "anthropic/claude-sonnet-4.5",
        "description": "均衡性能，适合企业级自动化",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 1000000
    },
    "(OpenRouter)google/gemini-3-pro-preview": {
        "id": "9",
        "base_url": "https://openrouter.ai/api/v1",
        "model_name": "google/gemini-3-pro-preview",
        "description": "擅长多模态与复杂推理，工程化能力强",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 1000000
    },
    "(OpenRouter)openai/gpt-5": {
        "id": "10",
        "base_url": "https://openrouter.ai/api/v1",
        "model_name": "openai/gpt-5",
        "description": "全能型模型，综合能力领先",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 400000
    },
    "(BigModel)bigmodel/glm-4.7": {
        "id": "11",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model_name": "glm-4.7",
        "description": "通用能力强，适合多轮对话",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 200000
    },
    "(BigModel)bigmodel/coding-plan": {
        "id": "12",
        "base_url": "https://open.bigmodel.cn/api/coding/paas/v4",
        "model_name": "glm-4.7",
        "description": "编码能力强，适合多轮对话",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 200000
    },
    "(Volcengine)byte/doubao-seed-code-plan": {
        "id": "13",
        "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
        "model_name": "doubao-seed-code-preview-latest",
        "description": "专攻编程",
        "input_price": 0.0,
        "output_price": 0.0,
        "context": 256000
    }
}


def get_model_max_context(model_name: str) -> int:
    if model_name not in BUILTIN_MODELS:
        return 0
    return BUILTIN_MODELS[model_name]["context"]