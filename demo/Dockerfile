# Key-free, offline demo image: the synthetic fixture swept by the model reader and drafter, with every model
# answer replayed from fixtures/recorded/. Built and removed by demo/run.sh; nothing in it holds a key.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev && useradd --uid 10001 --no-create-home demo
USER demo
ENTRYPOINT ["/bin/sh", "/app/demo/inside.sh"]
