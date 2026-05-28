from __future__ import annotations

import os
import threading
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

API_BASE = os.getenv("LLM_API_BASE", "")
API_KEY = os.getenv("LLM_API_KEY", "")
MODEL = os.getenv("LLM_MODEL", "gpt-4o")

# 线程安全的客户端缓存
_cache_lock = threading.Lock()
_cache: dict[tuple, OpenAI] = {}


def _get_client(api_base=None, api_key=None):
    key = (api_base or API_BASE, api_key or API_KEY)
    if not key[0] or not key[1]:
        raise RuntimeError("请先配置 API 接口信息")

    if key in _cache:
        return _cache[key]

    with _cache_lock:
        # 双重检查
        if key in _cache:
            return _cache[key]
        client = OpenAI(api_key=key[1], base_url=key[0])
        _cache[key] = client
        return client


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
            max_tokens=8192,
            timeout=120,
        )
        return response.choices[0].message.content or ""

    # 可取消模式：流式请求，在 chunk 间检查取消信号
    stream = client.chat.completions.create(
        model=model or MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=8192,
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
