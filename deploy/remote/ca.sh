#!/bin/sh
# 只读：导出 Caddy 自签根证书（公开信息，App 要内置它）
cd /opt/chat
echo "-----DOMAIN-----"; grep '^DOMAIN=' .env | cut -d= -f2
echo "-----CA-----"
docker compose exec -T caddy cat /data/caddy/pki/authorities/local/root.crt
echo "-----END-----"
