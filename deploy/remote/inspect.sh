#!/bin/sh
# 只读检查目标服务器：不修改任何东西。用于部署前确认端口、反向代理和资源占用。
echo "== 系统"; uname -a; cat /etc/os-release 2>/dev/null | head -3; uptime
echo "== CPU / 内存 / 硬盘"; nproc; free -h; df -h / /var/lib/docker 2>/dev/null
echo "== 公网 IP"; curl -s -m 5 https://api.ipify.org || true; echo
echo "== 监听端口"; (ss -tulpn 2>/dev/null || netstat -tulpn 2>/dev/null) | sed 's/users:.*//' | sort -u
echo "== Docker"; docker version --format '{{.Server.Version}}' 2>&1; docker compose version 2>&1
echo "== 运行中的容器"; docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}' 2>&1
echo "== Docker 网络"; docker network ls 2>&1
echo "== 反向代理"; for p in nginx caddy httpd apache2 traefik haproxy openresty; do pgrep -a "$p" | head -2; done
ls /etc/nginx/sites-enabled /etc/nginx/conf.d 2>/dev/null
echo "== 防火墙"; (ufw status 2>/dev/null; firewall-cmd --list-all 2>/dev/null) | head -30
