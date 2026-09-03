# Museek 後端 — 部署到 Cloud Run
#
# LLM 走 Azure OpenAI（公開端點），因此不需要 Tailscale。
# 若之後要讓雲端連內網的 llm-host，做法記在 NOTES.md #26。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENV PORT=8080
EXPOSE 8080

CMD ["./entrypoint.sh"]
