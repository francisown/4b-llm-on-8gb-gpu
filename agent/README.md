# Agent 第一课：模型、工具、观察和循环

这个目录包含一个不依赖 Agent 框架的最小推理运维 Agent。

## 它能做什么

- 通过 `check_service_health` 检查 vLLM、当前模型和推理网关；
- 通过 `get_gateway_queue_status` 查看网关 active / waiting 队列；
- 查看 GPU 型号、显存、利用率和温度；
- 根据真实工具结果生成中文结论。

所有工具均为只读白名单。用户输入不能变成任意 shell 命令。
每次工具执行完成后，程序会把该动作从下一轮的 JSON Schema 枚举中删除，
使小模型无法反复调用同一工具并形成死循环。

## Agent 循环

```text
用户问题
  -> 模型从严格 JSON Schema 中选择动作
  -> Python 执行白名单工具
  -> 工具观察结果返回模型
  -> 模型选择下一个动作或结束收集
  -> 单独的回答阶段根据全部证据生成最终回答
```

这里暂时没有使用 vLLM 的自由 `tool_choice=auto`。本地 Qwen3.5-4B
INT4 能生成工具意图，但实测自由生成 XML 时会漏掉分隔符，导致工具名解析错误。
强制指定工具可以正确工作。第一版改用严格结构化动作，使失败显式可见，后续会与
更强模型的原生 Tool Calling 做可靠性对比。

## 运行

先确保本地 vLLM 在 `127.0.0.1:8000`、Docker 网关在
`127.0.0.1:9000` 运行，然后在 WSL 中执行：

```bash
cd /mnt/e/AI-Inference-Lab
source /root/.venvs/ai-inference-bin/activate
python agent_lab/inference_agent.py
```

也可以只问一个问题：

```bash
python agent_lab/inference_agent.py "GPU现在用了多少显存？"
```

环境变量可覆盖默认地址和模型名：`VLLM_API_BASE`、`VLLM_HTTP_BASE`、
`GATEWAY_BASE`、`VLLM_MODEL`。
