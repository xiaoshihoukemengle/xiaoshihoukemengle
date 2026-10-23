# 服务端部署

一台机器上用 Docker Compose 跑完整服务端。组件和关键参数对齐 Element 官方的 ESS Community（ess-helm 26.10.2），方案说明见 [docs/README.md](../docs/README.md)。

| 服务 | 镜像版本 | 地址 | 作用 |
| --- | --- | --- | --- |
| Synapse | 1.163.1 | `matrix.域名` | 消息、房间、媒体、管理接口 |
| MAS | 1.27.1 | `auth.域名` | 注册、登录、邮箱验证、找回密码 |
| LiveKit | 1.13.10 | `rtc.域名` + 7881/tcp、7882/udp | 音视频 |
| lk-jwt-service | 0.9.0 | `rtc.域名/sfu/get` | 用 Matrix 身份换通话令牌 |
| ntfy | 2.33.0 | `push.域名` | 安卓自建推送（UnifiedPush） |
| Ketesa | 1.5.1 | `admin.域名` | 后台管理 |
| PostgreSQL / Valkey | 17 / 9.1.2 | 内部 | 数据库 / 缓存 |
| Caddy | 2.10 | 80、443 | HTTPS 与路由 |

联邦默认关闭：只对外提供客户端接口，不和其他 Matrix 服务器互通，也不连 matrix.org 取密钥。

## 本地试跑

需要 Docker、Python 3、openssl；跑网页测试还要 Node.js。

```sh
cd deploy
python3 manage.py init --domain chat.test --dev     # 自签证书 + mailpit 收信箱
docker compose --profile dev up -d
./tests/run_local.sh                                 # 接口 22 项 + 网页注册 5 项
```

本机浏览器或模拟器要访问 `chat.test`，需在 hosts 里把 `chat.test`、`matrix.chat.test`、`auth.chat.test`、`rtc.chat.test`、`admin.chat.test`、`push.chat.test` 指向本机，并信任 Caddy 的根证书（`docker compose exec caddy cat /data/caddy/pki/authorities/local/root.crt`）。开发环境的验证码邮件在 http://127.0.0.1:8025 查看。

## 正式部署

1. 域名解析：`域名`、`matrix.`、`auth.`、`rtc.`、`admin.`、`push.` 六条 A 记录指向服务器。域名定下后不能改（用户 ID 是 `@用户名:域名`）。
2. 防火墙放行 80、443（TCP + UDP）、7881/tcp、7882/udp。
3. 初始化并填 SMTP：

   ```sh
   python3 manage.py init --domain chat.example.com --node-ip 服务器公网IP --acme-email 你的邮箱 --app-name 应用名
   # 编辑 .env 里的 SMTP_HOST / SMTP_PORT / SMTP_MODE / SMTP_USERNAME / SMTP_PASSWORD / SMTP_FROM
   python3 manage.py render
   docker compose up -d
   ```

4. 建后台管理员：`python3 manage.py create-user admin --email 你的邮箱 --password '...' --admin`，然后打开 `https://admin.域名` 用它登录。
5. 验收：`python3 tests/smoke_test.py`。

`.env`、`keys/`、`config/` 里是密钥，不进 git，要单独备份。改了 `.env` 或 `templates/` 后运行 `python3 manage.py render` 并重启对应容器。

## 目前的取舍

- 登录和注册的按 IP 限流比 MAS 默认放宽（手机网络多人共用公网 IP），在 `.env` 的 `LOGIN_PER_IP_*`、`REGISTRATION_PER_IP_*` 调整。
- 只公开 `/.well-known/matrix/server` 和 `/_matrix/federation/v1/openid/userinfo` 两个联邦相关地址，通话授权服务要用它们核对用户身份，其余联邦接口一律 404。
- iOS 推送网关 Sygnal 等拿到超级签账号的 APNs 密钥后再加（阶段 3）。
- LiveKit 没开内置 TURN；极少数严格防火墙下可能连不上通话，阶段 3 实测后决定。
