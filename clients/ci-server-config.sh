#!/bin/sh
# CI 用：从仓库 Secrets 里的服务器地址算出 App 要连的域名，并取回服务器的自签根证书（server.yml 的 ca 任务上传的附件）。
# 没有配置服务器地址时什么都不做，App 仍按 brand.env 里的测试域名编译。
set -eu
[ -n "${SERVER_HOST:-}" ] || { echo "未配置服务器，使用 brand.env 里的域名"; exit 0; }
DASHED=$(echo "$SERVER_HOST" | tr . -)
DOMAIN="$DASHED.sslip.io"
echo "::add-mask::$DASHED"
echo "::add-mask::$DOMAIN"
echo "DOMAIN=$DOMAIN" >> "$GITHUB_ENV"
echo "PUBLIC_PORT=9443" >> "$GITHUB_ENV"
URL=$(gh api "repos/$GITHUB_REPOSITORY/actions/artifacts?name=ca-cert&per_page=1" --jq '.artifacts[0].archive_download_url')
[ -n "$URL" ] && [ "$URL" != null ] || { echo "找不到 ca-cert 附件，先运行服务器 ca 任务"; exit 1; }
gh api "$URL" > "$RUNNER_TEMP/ca.zip"
unzip -p "$RUNNER_TEMP/ca.zip" ca.pem > clients/ca.pem
openssl x509 -in clients/ca.pem -noout -subject -enddate
