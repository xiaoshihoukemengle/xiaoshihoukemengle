#!/usr/bin/env python3
"""服务端初始化与管理脚本（只用 Python 标准库 + openssl + docker）。

    python3 manage.py init --domain chat.example.com --node-ip 1.2.3.4 --acme-email you@example.com
    python3 manage.py init --domain chat.test --dev        # 本地开发：自签证书 + mailpit 收信
    python3 manage.py render                               # 改了 .env 或模板后重新生成 config/
    python3 manage.py create-user alice --email a@x.com --password '...' [--admin]
"""

import argparse
import base64
import os
import re
import secrets
import shutil
import string
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / ".env"
TEMPLATES = HERE / "templates"
CONFIG = HERE / "config"

SECRET_KEYS = [
    "POSTGRES_ADMIN_PASSWORD",
    "SYNAPSE_DB_PASSWORD",
    "MAS_DB_PASSWORD",
    "SYNAPSE_MACAROON_SECRET",
    "SYNAPSE_FORM_SECRET",
    "SYNAPSE_REGISTRATION_SHARED_SECRET",
    "MAS_SYNAPSE_SECRET",
    "LIVEKIT_SECRET",
    "RTC_AS_TOKEN",
    "RTC_HS_TOKEN",
]

# 模板文件 -> 生成到 config/ 下的位置
RENDER_MAP = {
    "synapse/homeserver.yaml": ["synapse/homeserver.yaml"],
    "synapse/log.yaml": ["synapse/log.yaml"],
    "synapse/rtc-registration.yaml": ["synapse/rtc-registration.yaml", "rtc/registration.yaml"],
    "mas/config.yaml": ["mas/config.yaml"],
    "livekit/livekit.yaml": ["livekit/livekit.yaml"],
    "ntfy/server.yml": ["ntfy/server.yml"],
    "well-known/client": ["well-known/client"],
    "well-known/server": ["well-known/server"],
}


def read_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def write_env(env):
    lines = ["# 由 manage.py init 生成。密钥不要提交到 git。"]
    lines += [f"{k}={v}" for k, v in env.items()]
    ENV_FILE.write_text("\n".join(lines) + "\n")
    os.chmod(ENV_FILE, 0o600)


def openssl(*args):
    subprocess.run(["openssl", *args], check=True, capture_output=True)


def generate_keys():
    """Synapse 签名密钥和 MAS 的 RSA / EC 密钥，只在不存在时生成。"""
    keys = HERE / "keys"
    keys.mkdir(exist_ok=True)
    signing = keys / "synapse-signing.key"
    if not signing.exists():
        # ed25519 私钥就是 32 字节随机种子，Synapse 用无填充 base64 存储
        seed = base64.b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        signing.write_text(f"ed25519 a_{secrets.token_hex(2)} {seed}\n")
    rsa = keys / "mas-rsa.pem"
    if not rsa.exists():
        openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(rsa))
    ec = keys / "mas-ec256.pem"
    if not ec.exists():
        openssl("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", str(ec))
    for path in keys.iterdir():
        os.chmod(path, 0o600)


def render(env):
    values = dict(env)
    values.setdefault("PUBLIC_PORT", "443")
    values["PORT_SUFFIX"] = "" if values["PUBLIC_PORT"] == "443" else ":" + values["PUBLIC_PORT"]
    values["DOMAIN_REGEX"] = re.escape(env["DOMAIN"]).replace("\\", "\\\\")
    if env.get("SMTP_USERNAME"):
        values["SMTP_AUTH"] = f"  username: {env['SMTP_USERNAME']}\n  password: {env['SMTP_PASSWORD']}"
    else:
        values["SMTP_AUTH"] = ""

    # 原地覆盖文件，不删目录：容器的目录挂载在目录被删后会失效
    for src, dests in RENDER_MAP.items():
        text = string.Template((TEMPLATES / src).read_text()).substitute(values)
        for dest in dests:
            out = CONFIG / dest
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text)

    # Caddyfile 用 Caddy 自己的 {$VAR} 环境变量语法，原样复制
    (CONFIG / "caddy").mkdir(parents=True, exist_ok=True)
    shutil.copy(TEMPLATES / "caddy/Caddyfile", CONFIG / "caddy/Caddyfile")
    if values["PUBLIC_PORT"] != "443":
        with open(CONFIG / "caddy/Caddyfile", "a") as f:
            f.write((TEMPLATES / "caddy/wellknown-443.caddy").read_text())

    keys = HERE / "keys"
    shutil.copy(keys / "synapse-signing.key", CONFIG / "synapse/signing.key")
    shutil.copy(keys / "mas-rsa.pem", CONFIG / "mas/rsa.pem")
    shutil.copy(keys / "mas-ec256.pem", CONFIG / "mas/ec256.pem")
    # 容器里的服务以非 root 用户运行（Synapse 991、MAS 65532），配置需要可读
    for path in CONFIG.rglob("*"):
        os.chmod(path, 0o755 if path.is_dir() else 0o644)
    print(f"已生成 {CONFIG}")


def cmd_init(args):
    env = read_env()
    if env and not args.force:
        print(".env 已存在，保留原有密钥，只更新传入的参数。")
    env["DOMAIN"] = args.domain or env.get("DOMAIN") or sys.exit("需要 --domain")
    env.setdefault("APP_NAME", args.app_name)
    if args.app_name != "Chat":
        env["APP_NAME"] = args.app_name
    env["PUBLIC_PORT"] = args.public_port or env.get("PUBLIC_PORT") or "443"
    env["PORT_SUFFIX"] = "" if env["PUBLIC_PORT"] == "443" else ":" + env["PUBLIC_PORT"]
    if args.public_port and args.public_port != "443":
        env["HTTP_PUBLISH"] = "127.0.0.1:18081:80"  # 不占用 80，也不对外开放
    if args.self_signed:
        # 没有域名的展示环境：Caddy 自签证书，通话授权服务回连时跳过校验
        env["CADDY_TLS"] = "internal"
        env["LKJWT_SKIP_TLS_VERIFY"] = "YES_I_KNOW_WHAT_I_AM_DOING"
        # 展示环境没有邮件服务：填占位值让 MAS 能启动，验证邮件发不出去，账号用 create-user 创建
        for key, value in (("SMTP_HOST", "localhost"), ("SMTP_PORT", "25"), ("SMTP_MODE", "plain"),
                           ("SMTP_FROM", f"noreply@{env['DOMAIN']}")):
            if not env.get(key):
                env[key] = value
        env.setdefault("SMTP_USERNAME", "")
        env.setdefault("SMTP_PASSWORD", "")
    elif args.dev:
        env["CADDY_TLS"] = "internal"
        env.update(SMTP_HOST="mailpit", SMTP_PORT="1025", SMTP_MODE="plain", SMTP_USERNAME="", SMTP_PASSWORD="")
        env.setdefault("SMTP_FROM", f"noreply@{env['DOMAIN']}")
        env.setdefault("LIVEKIT_NODE_IP", args.node_ip or "127.0.0.1")
        # 开发环境是自签证书，通话授权服务回连域名时跳过证书校验
        env["LKJWT_SKIP_TLS_VERIFY"] = "YES_I_KNOW_WHAT_I_AM_DOING"
    else:
        env["CADDY_TLS"] = args.acme_email or env.get("CADDY_TLS") or sys.exit("正式环境需要 --acme-email")
        env["LKJWT_SKIP_TLS_VERIFY"] = ""
        for key in ("SMTP_HOST", "SMTP_PORT", "SMTP_MODE", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM"):
            env.setdefault(key, "")
    if args.node_ip:
        env["LIVEKIT_NODE_IP"] = args.node_ip
    env.setdefault("LIVEKIT_NODE_IP", "")
    if not env["LIVEKIT_NODE_IP"]:
        sys.exit("需要 --node-ip（服务器公网 IP，通话媒体流用）")
    env.setdefault("MAX_UPLOAD_SIZE", "200M")
    env.setdefault("REGISTRATION_TOKEN_REQUIRED", "false")
    env.setdefault("LOGIN_PER_IP_BURST", "10")
    env.setdefault("LOGIN_PER_IP_RATE", "0.2")
    env.setdefault("REGISTRATION_PER_IP_BURST", "10")
    env.setdefault("REGISTRATION_PER_IP_RATE", "0.01")
    env.setdefault("LIVEKIT_KEY", "matrix-rtc")
    env.setdefault("MAS_ENCRYPTION_SECRET", secrets.token_hex(32))
    for key in SECRET_KEYS:
        if args.force or not env.get(key):
            env[key] = secrets.token_urlsafe(32)
    write_env(env)
    generate_keys()
    render(env)
    if not env.get("SMTP_HOST"):
        print("提醒：还没配置 SMTP，注册收不到验证邮件。在 .env 里填 SMTP_* 后运行 python3 manage.py render。")


def cmd_render(_args):
    render(read_env())


def compose(*args, **kwargs):
    return subprocess.run(["docker", "compose", *args], cwd=HERE, **kwargs)


def cmd_create_user(args):
    cmd = ["exec", "-T", "mas", "mas-cli", "--config", "/config/config.yaml", "manage", "register-user",
           "--yes", "--ignore-password-complexity", args.username]
    if args.email:
        cmd += ["--email", args.email]
    if args.password:
        cmd += ["--password", args.password]
    if args.admin:
        cmd += ["--admin"]
    sys.exit(compose(*cmd).returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="生成 .env、密钥和配置")
    p.add_argument("--domain", help="服务器域名，定下来就不能改，用户 ID 形如 @alice:域名")
    p.add_argument("--app-name", default="Chat")
    p.add_argument("--node-ip", help="服务器公网 IP（LiveKit 媒体流）")
    p.add_argument("--acme-email", help="Let's Encrypt 证书联系邮箱（正式环境）")
    p.add_argument("--public-port", help="对外 HTTPS 端口，默认 443；443 被占用时换一个")
    p.add_argument("--self-signed", action="store_true", help="用 Caddy 自签证书（没有域名的展示环境）")
    p.add_argument("--dev", action="store_true", help="本地开发：自签证书 + mailpit")
    p.add_argument("--force", action="store_true", help="重新生成所有密钥（会让已有数据失效）")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("render", help="按 .env 重新生成 config/")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("create-user", help="直接创建账号（不走邮箱验证）")
    p.add_argument("username")
    p.add_argument("--email")
    p.add_argument("--password")
    p.add_argument("--admin", action="store_true", help="可登录后台的管理员")
    p.set_defaults(func=cmd_create_user)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
