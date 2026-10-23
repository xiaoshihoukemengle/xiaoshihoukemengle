#!/bin/sh
# 本地开发环境一键验收：服务端接口 24 项 + 网页注册流程 5 项。
# 前提：python3 manage.py init --domain chat.test --dev && docker compose --profile dev up -d
set -eu
cd "$(dirname "$0")/.."
DOMAIN=$(grep '^DOMAIN=' .env | cut -d= -f2)
CA=$(mktemp)
docker compose exec -T caddy cat /data/caddy/pki/authorities/local/root.crt > "$CA"
python3 tests/smoke_test.py --resolve 127.0.0.1 --cafile "$CA"
cd tests/web
[ -d node_modules ] || npm install --silent
DOMAIN=$DOMAIN RESOLVE=127.0.0.1 node register.mjs
