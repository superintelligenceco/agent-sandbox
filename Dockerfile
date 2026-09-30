# syntax=docker/dockerfile:1

FROM python:3.14-slim AS build
WORKDIR /src
RUN pip install --no-cache-dir build==1.2.2
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

FROM python:3.14-slim
LABEL org.opencontainers.image.title="agent-sandbox" \
      org.opencontainers.image.description="Self-hostable disposable sandboxes for AI agents, with snapshot, rollback, and fork." \
      org.opencontainers.image.source="https://github.com/superintelligenceco/agent-sandbox" \
      org.opencontainers.image.licenses="Apache-2.0"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENT_SANDBOX_HOST=0.0.0.0 \
    AGENT_SANDBOX_PORT=8080 \
    AGENT_SANDBOX_DATA_DIR=/data
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir "$(ls /tmp/*.whl)[server]" && rm /tmp/*.whl \
    && useradd --system --uid 10001 --no-create-home --home-dir /data agent-sandbox \
    && install -d -o 10001 -g 0 -m 0770 /data
# The server needs the Docker socket, and the socket's group ID differs between
# hosts. Run as the agent-sandbox user and add the socket's group with
# `group_add`, or run as root. See the security model in the README.
USER agent-sandbox
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4)"
ENTRYPOINT ["agent-sandbox"]
CMD ["serve"]
