import os
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

# 用项目根目录的绝对路径加载 .env，避免 Flask reloader 切换 CWD 导致加载失败
load_dotenv(Path(__file__).parent.parent / ".env")

API_BASE = os.getenv("LLM_API_BASE", "")
API_KEY = os.getenv("LLM_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o")

_client = None


def _get_client():
    global _client
    if _client is None:
        if not API_KEY or not API_BASE:
            raise RuntimeError("请先配置 .env 文件中的 LLM_API_BASE 和 LLM_API_KEY")
        _client = OpenAI(api_key=API_KEY, base_url=API_BASE)
    return _client


def call_llm(prompt: str, system_prompt: str = "") -> str:
    client = _get_client()
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=2048,
    )
    return response.choices[0].message.content or ""
