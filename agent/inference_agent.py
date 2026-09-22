"""A minimal local inference-operations agent.

The model chooses a structured action. Python executes only a fixed allowlist
of read-only tools and feeds the observation back to the model.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from openai import OpenAI


VLLM_API_BASE = os.getenv("VLLM_API_BASE", "http://127.0.0.1:8000/v1")
VLLM_HTTP_BASE = os.getenv("VLLM_HTTP_BASE", "http://127.0.0.1:8000")
GATEWAY_BASE = os.getenv("GATEWAY_BASE", "http://127.0.0.1:9000")
MODEL_NAME = os.getenv("VLLM_MODEL", "Qwen3.5-4B-INT4-AWQ-self")
MAX_STEPS = 4


def http_get(url: str, timeout: float = 5.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            try:
                body: Any = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                body = raw
            return {"reachable": True, "status_code": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        return {"reachable": True, "status_code": exc.code, "body": body}
    except Exception as exc:  # Network failures are observations, not agent crashes.
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"}


def check_vllm_health() -> dict[str, Any]:
    health = http_get(f"{VLLM_HTTP_BASE}/health")
    models_response = http_get(f"{VLLM_HTTP_BASE}/v1/models")
    models: list[dict[str, Any]] = []
    body = models_response.get("body")
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        for item in body["data"]:
            if isinstance(item, dict):
                models.append(
                    {
                        "id": item.get("id"),
                        "max_model_len": item.get("max_model_len"),
                    }
                )
    return {
        "reachable": health.get("reachable", False),
        "status_code": health.get("status_code"),
        "models": models,
    }


def check_gateway_health() -> dict[str, Any]:
    live = http_get(f"{GATEWAY_BASE}/live")
    dependency = http_get(f"{GATEWAY_BASE}/health")
    return {
        "live_status_code": live.get("status_code"),
        "dependency_status_code": dependency.get("status_code"),
        "dependency": dependency.get("body"),
    }


def check_all_health() -> dict[str, Any]:
    return {
        "vllm": check_vllm_health(),
        "gateway": check_gateway_health(),
    }


def get_gateway_load() -> dict[str, Any]:
    return {"gateway_load": http_get(f"{GATEWAY_BASE}/gateway/status")}


def get_gpu_status() -> dict[str, Any]:
    command = [
        "nvidia-smi",
        "--query-gpu=name,driver_version,memory.used,memory.total,utilization.gpu,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}

    fields = [part.strip() for part in completed.stdout.strip().split(",")]
    if len(fields) != 6:
        return {"available": False, "error": "unexpected nvidia-smi output"}
    name, driver, used, total, utilization, temperature = fields
    return {
        "available": True,
        "name": name,
        "driver_version": driver,
        "memory_used_mib": int(used),
        "memory_total_mib": int(total),
        "gpu_utilization_percent": int(utilization),
        "temperature_c": int(temperature),
    }


TOOLS: dict[str, Callable[[], dict[str, Any]]] = {
    "check_service_health": check_all_health,
    "get_gpu_status": get_gpu_status,
    "get_gateway_queue_status": get_gateway_load,
}


def build_action_schema(completed_actions: set[str]) -> dict[str, Any]:
    """Remove completed actions so the model cannot loop on the same tool."""
    available_actions = [name for name in TOOLS if name not in completed_actions]
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [*available_actions, "final"],
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }


SYSTEM_PROMPT = """你是本地 AI 推理运维 Agent 的决策器。
你的任务是回答用户关于 vLLM、推理网关、GPU 和网关负载的问题。
规则：
1. 实时状态必须来自工具，绝对不能凭常识猜测。
2. 没有足够观察结果时选择一个工具动作。
3. 已经获得足够证据时选择 final。
4. 必须回答用户问题的每一部分，不要重复已经成功执行的动作。
5. 工具都是只读的；你没有重启、删除或修改系统的权限。
动作选择：
- 服务是否正常、能否连接、模型是否启动：check_service_health
- GPU、显存、利用率、温度：get_gpu_status
- 网关排队、active、waiting、并发：get_gateway_queue_status
"""


def decide(
    client: OpenAI,
    messages: list[dict[str, str]],
    completed_actions: set[str],
) -> str:
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0,
        max_tokens=32,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "inference_agent_action",
                "strict": True,
                "schema": build_action_schema(completed_actions),
            },
        },
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("model returned an empty decision")
    decision = json.loads(content)
    return str(decision["action"])


def make_final_answer(
    client: OpenAI,
    question: str,
    observations: list[dict[str, Any]],
) -> str:
    evidence = json.dumps(observations, ensure_ascii=False, separators=(",", ":"))
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": (
                    "只根据提供的工具证据回答用户原问题。用中文简洁回答，包含关键数值；"
                    "不要编造证据中没有的信息，不要提及内部动作名。"
                ),
            },
            {
                "role": "user",
                "content": f"原问题：{question}\n工具证据：{evidence}",
            },
        ],
        temperature=0,
        max_tokens=192,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    return (response.choices[0].message.content or "").strip()


def run_agent(question: str, *, show_trace: bool = True) -> str:
    client = OpenAI(base_url=VLLM_API_BASE, api_key="local-vllm")
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    completed_actions: set[str] = set()
    observations: list[dict[str, Any]] = []

    for step in range(1, MAX_STEPS + 1):
        action = decide(client, messages, completed_actions)

        if show_trace:
            print(f"[步骤 {step}] 模型选择：{action}")

        if action == "final":
            answer = make_final_answer(client, question, observations)
            if answer:
                return answer
            messages.append(
                {
                    "role": "user",
                    "content": "最终回答生成失败，请重新选择 final。",
                }
            )
            continue

        if action in completed_actions:
            messages.append(
                {
                    "role": "user",
                    "content": f"动作 {action} 已经执行过，请使用已有观察或选择其他动作。",
                }
            )
            continue

        tool = TOOLS[action]
        observation = tool()
        completed_actions.add(action)
        observations.append({"action": action, "result": observation})
        compact_observation = json.dumps(observation, ensure_ascii=False, separators=(",", ":"))

        if show_trace:
            print(f"[工具结果] {compact_observation}")

        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": json.dumps({"action": action}, ensure_ascii=False),
                },
                {
                    "role": "user",
                    "content": (
                        f"动作 {action} 的真实观察结果如下：\n{compact_observation}\n"
                        "请判断是否已足以回答原问题；不足则选择尚未执行的动作。"
                    ),
                },
            ]
        )

    raise RuntimeError(f"agent exceeded the maximum of {MAX_STEPS} steps")


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal local inference operations agent")
    parser.add_argument("question", nargs="*", help="single question; omit for interactive mode")
    parser.add_argument("--no-trace", action="store_true", help="hide action and observation trace")
    args = parser.parse_args()

    if args.question:
        print(run_agent(" ".join(args.question), show_trace=not args.no_trace))
        return

    print("本地推理运维 Agent。输入 /exit 退出。")
    while True:
        try:
            question = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if question.lower() in {"/exit", "exit", "quit"}:
            return
        if not question:
            continue
        try:
            print(f"Agent> {run_agent(question, show_trace=not args.no_trace)}")
        except Exception as exc:
            print(f"Agent运行失败：{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
