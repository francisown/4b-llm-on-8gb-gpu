#!/usr/bin/env python3
"""A small, robust multi-turn chat client for the local vLLM server."""

from __future__ import annotations

import os
import re
import sys
import time

from openai import OpenAI
from openai import BadRequestError


BASE_URL = os.environ.get("VLLM_BASE_URL", "http://127.0.0.1:8000/v1")
MODEL = os.environ.get("VLLM_MODEL", "Qwen3.5-4B-INT4-AWQ-self")
MAX_OUTPUT_TOKENS = int(os.environ.get("VLLM_MAX_OUTPUT_TOKENS", "256"))
MAX_HISTORY_TURNS = int(os.environ.get("VLLM_MAX_HISTORY_TURNS", "6"))


def normalize_unicode(text: str) -> str:
    """Combine valid surrogate pairs and replace any isolated surrogate."""
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def hide_empty_thinking(text: str) -> str:
    return re.sub(r"^\s*<think>\s*</think>\s*", "", text, count=1)


def parse_thinking_switch(text: str) -> tuple[str, bool]:
    """Return prompt text and whether the Qwen chat template should think."""
    lowered = text.lower()
    enabled = lowered.endswith("/think") and not lowered.endswith("/no_think")
    text = re.sub(r"\s*/(?:no_)?think\s*$", "", text, flags=re.IGNORECASE)
    return text, enabled


def drop_oldest_turn(conversation: list[dict[str, str]]) -> bool:
    """Drop the oldest user/assistant pair while keeping the newest question."""
    if len(conversation) < 3:
        return False
    del conversation[:2]
    return True


def main() -> int:
    client = OpenAI(base_url=BASE_URL, api_key="EMPTY")

    try:
        available = [item.id for item in client.models.list().data]
    except Exception as exc:
        print("无法连接本地 vLLM 服务。请先启动模型服务器。")
        print(f"地址：{BASE_URL}")
        print(f"错误：{exc}")
        return 1

    if MODEL not in available:
        print(f"找不到模型 {MODEL}，当前模型：{', '.join(available)}")
        return 1

    print(f"已连接：{MODEL}")
    print(
        "直接输入问题并回车。/clear 清空历史，/exit 退出；"
        "问题末尾加 /think 可开启思考。"
    )
    print(
        f"每轮最多输出 {MAX_OUTPUT_TOKENS} token；保留最近 {MAX_HISTORY_TURNS} 轮，"
        "接近上下文上限时会自动删除最早历史。"
    )

    conversation: list[dict[str, str]] = []

    while True:
        try:
            user_text = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0

        if not user_text:
            continue
        if user_text.lower() in {"/exit", "/quit", "exit", "quit", "退出"}:
            print("已退出。")
            return 0
        if user_text.lower() == "/clear":
            conversation.clear()
            print("对话历史已清空。")
            continue

        prompt_text, enable_thinking = parse_thinking_switch(user_text)
        safe_user_text = normalize_unicode(prompt_text)
        conversation.append({"role": "user", "content": safe_user_text})

        while len(conversation) > MAX_HISTORY_TURNS * 2 + 1:
            drop_oldest_turn(conversation)

        trimmed_turns = 0
        request_started = time.perf_counter()
        while True:
            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=conversation,
                    stream=False,
                    temperature=0.6,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    extra_body={
                        "chat_template_kwargs": {"enable_thinking": enable_thinking}
                    },
                )
                break
            except BadRequestError as exc:
                if "maximum context length" in str(exc) and drop_oldest_turn(conversation):
                    trimmed_turns += 1
                    continue
                if conversation and conversation[-1]["role"] == "user":
                    conversation.pop()
                print(f"请求失败：{exc}")
                response = None
                break
            except Exception as exc:
                if conversation and conversation[-1]["role"] == "user":
                    conversation.pop()
                print(f"请求失败：{exc}")
                response = None
                break

        if response is None:
            continue
        if trimmed_turns:
            print(f"[上下文接近上限，已自动删除最早的 {trimmed_turns} 轮历史]")

        answer = normalize_unicode(response.choices[0].message.content or "")
        conversation.append({"role": "assistant", "content": answer})
        print(f"AI> {hide_empty_thinking(answer)}")
        usage = response.usage
        elapsed = time.perf_counter() - request_started
        completion_tokens = usage.completion_tokens if usage else 0
        e2e_tps = completion_tokens / elapsed if elapsed > 0 else 0.0
        print(
            f"[{completion_tokens} tokens，{elapsed:.2f} 秒，"
            f"端到端 {e2e_tps:.2f} tok/s]"
        )


if __name__ == "__main__":
    raise SystemExit(main())
