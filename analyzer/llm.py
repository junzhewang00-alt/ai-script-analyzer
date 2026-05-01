import os
import threading
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

API_BASE = os.getenv("LLM_API_BASE", "")
API_KEY = os.getenv("LLM_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o")

_client = None
_client_config = None


def _get_client(api_base=None, api_key=None):
    global _client, _client_config
    key = (api_base, api_key)
    if key == _client_config and _client is not None:
        return _client
    if not api_key or not api_base:
        if not API_KEY or not API_BASE:
            raise RuntimeError("请先配置 API 接口信息")
        _client_config = (API_BASE, API_KEY)
        _client = OpenAI(api_key=API_KEY, base_url=API_BASE)
        return _client
    _client_config = key
    _client = OpenAI(api_key=api_key, base_url=api_base)
    return _client


def get_config():
    return {"api_base": API_BASE, "api_key": API_KEY, "model": MODEL}


def call_llm(prompt: str, system_prompt: str = "",
             api_base=None, api_key=None, model=None,
             cancel_event: threading.Event = None):
    client = _get_client(api_base=api_base, api_key=api_key)
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    if cancel_event is None:
        response = client.chat.completions.create(
            model=model or MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=4096,
            timeout=120,
        )
        return response.choices[0].message.content or ""

    # 可取消模式：流式请求，在 chunk 间检查取消信号
    stream = client.chat.completions.create(
        model=model or MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=4096,
        timeout=120,
        stream=True,
    )
    chunks = []
    try:
        for chunk in stream:
            if cancel_event.is_set():
                stream.close()
                raise RuntimeError("分析已取消")
            delta = chunk.choices[0].delta
            if getattr(delta, "content", None):
                chunks.append(delta.content)
    finally:
        stream.close()
    return "".join(chunks)
