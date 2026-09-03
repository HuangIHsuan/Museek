#!/bin/sh
# Cloud Run 啟動腳本。
#
# 正常情況直接啟動應用程式——LLM 走 Azure OpenAI（公開端點），不需要 Tailscale。
# 若之後要讓雲端連內網的 llm-host，把 tailscaled 裝回 image 即可（NOTES.md #26），
# 這裡的分支會自動生效。
set -e

if [ -n "$TS_AUTHKEY" ]; then
  if [ -x /usr/sbin/tailscaled ]; then
    echo "[entrypoint] 啟動 tailscaled（userspace）..."
    /usr/sbin/tailscaled \
      --tun=userspace-networking \
      --socks5-server=localhost:1055 \
      --outbound-http-proxy-listen=localhost:1055 \
      --state=mem: &
    /usr/bin/tailscale up \
      --authkey="${TS_AUTHKEY}" \
      --hostname="${TS_HOSTNAME:-museek-cloudrun}" \
      --accept-routes
    /usr/bin/tailscale status || true
  else
    echo "[entrypoint] 有 TS_AUTHKEY 但 image 裡沒有 tailscaled——見 NOTES.md #26" >&2
  fi
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}" --workers 1
