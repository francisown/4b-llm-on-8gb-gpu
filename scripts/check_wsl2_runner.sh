#!/usr/bin/env bash
# 只读自检：确认本机 vLLM 是否真的"不支持 V2 model runner"。
# 不启动服务、不修改任何配置。请在 WSL2 内运行。
set -uo pipefail

VENV_DIR="${VENV_DIR:-/root/.venvs/ai-inference-week1}"

echo "===== 1. 是否在 WSL 内 / 内核版本 ====="
if grep -qi microsoft /proc/version 2>/dev/null; then
  echo "在 WSL 内：是"
else
  echo "在 WSL 内：否 —— 这个脚本是给 WSL2 用的，结论不适用当前环境"
fi
echo "内核版本：$(uname -r)"
echo "（上游对 pinned memory 的门槛是内核 >= 4.19.121）"

echo
echo "===== 2. vLLM / PyTorch / UVA ====="
if [ -f "$VENV_DIR/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
else
  echo "警告：未找到 venv $VENV_DIR，将使用当前 python"
fi

# 用 python 自己解析包路径，避免手写 lib/ 层级出错
VLLM_PKG="$(python -c 'import os, vllm; print(os.path.dirname(vllm.__file__))' 2>/dev/null || true)"
if [ -n "$VLLM_PKG" ]; then
  echo "vLLM 包路径：$VLLM_PKG"
else
  echo "警告：无法解析 vllm 包路径，后续源码检查会跳过"
fi

python - <<'PY'
try:
    import vllm
    print("vllm:", vllm.__version__)
except Exception as e:
    print("vllm 导入失败:", type(e).__name__, e)
try:
    import torch
    print("torch:", torch.__version__)
    print("cuda available:", torch.cuda.is_available())
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        print("device:", p.name)
        print("total_memory_GiB:", round(p.total_memory / 1024**3, 2))
        print("unified_addressing(UVA):", getattr(p, "unified_addressing", "<该 torch 版本无此属性，属正常>"))
except Exception as e:
    print("torch 检查失败:", type(e).__name__, e)
PY

echo
echo "===== 3. VLLM_WSL2_ENABLE_PIN_MEMORY 开关是否存在 ====="
if [ -n "$VLLM_PKG" ] && grep -rq "VLLM_WSL2_ENABLE_PIN_MEMORY" "$VLLM_PKG" 2>/dev/null; then
  echo "结果：存在。相关位置："
  grep -rn "VLLM_WSL2_ENABLE_PIN_MEMORY" "$VLLM_PKG" 2>/dev/null | head -8
else
  echo "结果：未找到。这个 vLLM 版本可能还没有该开关，验证路线需要调整。"
fi

echo
echo "===== 4. pinned memory 门控代码（关键判断依据）====="
if [ -n "$VLLM_PKG" ] && [ -f "$VLLM_PKG/platforms/cuda.py" ]; then
  echo "--- $VLLM_PKG/platforms/cuda.py 中给出开关注释/返回值的上下文 ---"
  grep -n -B3 -A6 "VLLM_WSL2_ENABLE_PIN_MEMORY" "$VLLM_PKG/platforms/cuda.py" 2>/dev/null
else
  echo "跳过：未找到 platforms/cuda.py"
fi

echo
echo "===== 5. V2 runner 与 UVA 相关代码路径 ====="
if [ -n "$VLLM_PKG" ]; then
  grep -rn "uva_instead_of_gpu\|_get_v2_model_runner_unsupported_features\|require.*UVA\|requires UVA" "$VLLM_PKG" 2>/dev/null | head -12
else
  echo "跳过：未找到 vllm 包路径"
fi

echo
echo "===== 6. 不带开关时 pinned memory ====="
python - <<'PY'
try:
    from vllm.platforms import current_platform as cp
    fn = getattr(cp, "is_pin_memory_available", None)
    print("is_pin_memory_available():", fn() if fn else "<该版本无此方法>")
except Exception as e:
    print("检查失败:", type(e).__name__, e)
PY

echo
echo "===== 7. 【关键】带上开关后 pinned memory 是否可用（不启动服务）====="
VLLM_WSL2_ENABLE_PIN_MEMORY=1 python - <<'PY'
import os
print("环境变量 VLLM_WSL2_ENABLE_PIN_MEMORY =", os.getenv("VLLM_WSL2_ENABLE_PIN_MEMORY"))
try:
    import vllm.envs as envs
    print("envs.VLLM_WSL2_ENABLE_PIN_MEMORY =", envs.VLLM_WSL2_ENABLE_PIN_MEMORY)
except Exception as e:
    print("读取 envs 失败:", type(e).__name__, e)
try:
    from vllm.platforms import current_platform as cp
    fn = getattr(cp, "is_pin_memory_available", None)
    print("is_pin_memory_available():", fn() if fn else "<该版本无此方法>")
except Exception as e:
    print("检查失败:", type(e).__name__, e)
PY

echo
echo "===== 8. 尝试读取 v2 runner 的选择结果 ====="
VLLM_WSL2_ENABLE_PIN_MEMORY=1 python - <<'PY'
try:
    from vllm.platforms import current_platform as cp
    for name in ("use_v2_model_runner", "_get_v2_model_runner_unsupported_features"):
        fn = getattr(cp, name, None)
        if fn is None:
            print(f"{name}: <该版本无此方法>")
        elif callable(fn):
            try:
                print(f"{name}():", fn())
            except Exception as e:
                print(f"{name}() 调用失败:", type(e).__name__, e)
        else:
            print(f"{name} =", fn)
except Exception as e:
    print("检查失败:", type(e).__name__, e)
PY

echo
echo "===== 自检结束 ====="
echo "第 6 与第 7 步的对比是关键：如果第 7 步变成 True，说明开关生效，V2 runner 有戏。"
