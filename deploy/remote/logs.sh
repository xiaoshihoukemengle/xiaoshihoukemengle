#!/bin/sh
# 只读：查看 chat 项目各容器状态和最近日志
cd /opt/chat
docker compose ps -a --format 'table {{.Name}}\t{{.Status}}'
for s in mas synapse caddy; do echo "== $s"; docker compose logs --tail 40 --no-log-prefix "$s" 2>&1 | cut -c1-300; done
