#!/bin/sh
# 创建展示用账号（已存在则跳过）
cd /opt/chat
for u in test test2; do
  if python3 manage.py create-user "$u" --password test123 2>&1 | tail -3; then :; fi
done
