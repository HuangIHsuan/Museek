#!/bin/bash
# Firestore TTL 政策（開發文件 §13 合規檢核：video_cache 30 天）
#
# Firestore 的 TTL 語意是「expires_at 欄位時間到就刪」，跟 MongoDB 的
# expireAfterSeconds 不同，因此寫入端一律填明確的 expires_at（見 firestore_repo.py）。
set -euo pipefail
PROJECT="${1:?用法: setup_firestore_ttl.sh <PROJECT_ID>}"
GCLOUD="${GCLOUD:-$HOME/.museek-tools/gcloud}"

for COLLECTION in video_cache taste_profiles; do
  echo "設定 $COLLECTION.expires_at 的 TTL 政策..."
  "$GCLOUD" firestore fields ttls update expires_at \
    --collection-group="$COLLECTION" --enable-ttl \
    --project="$PROJECT" --quiet
done
echo "完成。查看：gcloud firestore fields ttls list --project=$PROJECT"
