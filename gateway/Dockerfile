ARG PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.10-slim
FROM ${PYTHON_IMAGE}

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app

COPY requirements.txt ./
RUN python -m pip install \
    --no-cache-dir \
    --index-url "${PIP_INDEX_URL}" \
    --timeout 120 \
    -r requirements.txt

COPY gateway.py index.html ./

USER app
EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/live', timeout=2)"]

CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "9000"]
