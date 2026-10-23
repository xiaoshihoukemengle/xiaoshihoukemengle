#!/bin/sh
# 在服务器上部署（可重复运行）：只动 /opt/chat 和这套 Compose 项目（名为 chat），
# 不碰已有容器、系统配置和现有防火墙规则（只新增 3 条放行）。
# 参数 $1：服务器公网 IP。域名用 sslip.io（把 IP 写进主机名的公共 DNS，只做解析），证书是 Caddy 自签的。
set -eu
IP=${1:?需要服务器 IP}
D=/opt/chat
DOM="$(echo "$IP" | tr . -).sslip.io"
PORT=9443
cd "$D"

echo "== 检查依赖"
for c in python3 openssl docker curl ss; do command -v "$c" >/dev/null || { echo "缺少 $c"; exit 1; }; done
docker compose version >/dev/null

echo "== 检查端口是否空闲（本项目已在运行时跳过）"
if ! docker compose -p chat ps -q 2>/dev/null | grep -q .; then
  for p in $PORT 7881 7882 18081; do
    if ss -H -tuln | grep -qE "[:.]$p\b"; then echo "端口 $p 已被占用，停止部署"; exit 1; fi
  done
fi

echo "== 初始化配置"
# init 可重复运行：已有密钥保留，只更新参数并重新生成配置
python3 manage.py init --domain "$DOM" --public-port "$PORT" --self-signed --node-ip "$IP" --app-name "${APP_NAME:-Chat}"

echo "== 防火墙：新增放行（已有规则不动）"
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow "$PORT/tcp" comment 'chat https'
  ufw allow 7881/tcp comment 'chat livekit'
  ufw allow 7882/udp comment 'chat livekit'
fi

echo "== 拉镜像并启动"
docker compose pull -q
docker compose up -d
echo "== 等待服务就绪"
i=0
until [ "$(docker compose ps --format '{{.Status}}' synapse | grep -c healthy)" = 1 ]; do
  i=$((i+1)); [ $i -gt 60 ] && { docker compose ps; docker compose logs --tail 40 synapse mas; exit 1; }
  sleep 5
done
docker compose ps --format 'table {{.Name}}\t{{.Status}}\t{{.Ports}}'

echo "== 验收"
CA=$(mktemp)
docker compose exec -T caddy cat /data/caddy/pki/authorities/local/root.crt > "$CA"
python3 tests/smoke_test.py --resolve 127.0.0.1 --cafile "$CA" 2>&1 | tail -40 || true
echo "== 域名"; echo "$DOM:$PORT"
echo "== 根证书（公开信息，App 要内置它）"; cat "$CA"
rm -f "$CA"
