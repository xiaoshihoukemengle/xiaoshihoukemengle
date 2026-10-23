#!/usr/bin/env python3
"""服务端验收脚本：对一套跑起来的服务逐项检查，任何一项失败就退出码非 0。

    python3 tests/smoke_test.py                  # 读 ../.env 里的 DOMAIN，直接访问域名
    python3 tests/smoke_test.py --resolve 127.0.0.1 --cafile caddy-root.crt   # 本地开发（自签证书）

只用 Python 标准库。账号用 mas-cli 直接创建（网页注册流程由 web_register.mjs 单独测）。
"""

import argparse
import base64
import json
import secrets
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEPLOY = Path(__file__).resolve().parent.parent

results = []
PS = ""  # 非 443 端口时形如 ":9443"，main() 里按 .env 设置


def check(name):
    def wrap(fn):
        def run(*args, **kwargs):
            try:
                value = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - 汇总每一项的失败原因
                results.append((name, False, f"{type(exc).__name__}: {exc}"))
                print(f"  FAIL {name}: {exc}")
                return None
            results.append((name, True, ""))
            print(f"  ok   {name}")
            return value
        return run
    return wrap


class Client:
    def __init__(self, domain, context):
        self.domain = domain
        self.context = context

    def request(self, method, url, body=None, token=None, headers=None, raw=False):
        data = None
        hdrs = dict(headers or {})
        if body is not None and not isinstance(body, bytes):
            data = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        elif body is not None:
            data = body
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = resp.read()
                status = resp.status
        except urllib.error.HTTPError as err:
            payload = err.read()
            status = err.code
        if raw:
            return status, payload
        try:
            return status, json.loads(payload or b"{}")
        except json.JSONDecodeError:
            return status, {"_raw": payload[:200].decode(errors="replace")}

    def hs(self, path):
        return f"https://matrix.{self.domain}{PS}{path}"


def expect(status, body, want=200):
    if status != want:
        raise AssertionError(f"HTTP {status}（期望 {want}）：{json.dumps(body, ensure_ascii=False)[:300]}")
    return body


def mas_cli(*args):
    cmd = ["docker", "compose", "exec", "-T", "mas", "mas-cli", "--config", "/config/config.yaml", *args]
    out = subprocess.run(cmd, cwd=DEPLOY, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"mas-cli {' '.join(args[:3])} 失败：{out.stderr.strip()[-300:]}")
    return out.stdout + out.stderr


def read_env():
    env = {}
    for line in (DEPLOY / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            env[key] = value
    return env


def jwt_payload(token):
    part = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain")
    parser.add_argument("--resolve", help="把 *.域名 解析到这个 IP（本地开发用）")
    parser.add_argument("--cafile", help="信任的根证书（Caddy 自签证书）")
    args = parser.parse_args()

    env = read_env()
    domain = args.domain or env["DOMAIN"]
    global PS
    PS = env.get("PORT_SUFFIX", "")

    if args.resolve:
        real = socket.getaddrinfo

        def fake(host, *rest, **kw):
            if host == domain or str(host).endswith("." + domain):
                host = args.resolve
            return real(host, *rest, **kw)
        socket.getaddrinfo = fake

    context = ssl.create_default_context(cafile=args.cafile) if args.cafile else ssl.create_default_context()
    if args.resolve:
        handlers = [urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)]
    else:
        handlers = [urllib.request.HTTPSHandler(context=context)]
    urllib.request.install_opener(urllib.request.build_opener(*handlers))
    c = Client(domain, context)
    run_id = secrets.token_hex(3)
    password = "Test-" + secrets.token_urlsafe(12)
    print(f"域名 {domain}，本次测试账号后缀 {run_id}")

    print("\n[1] 服务发现与联邦")

    @check("well-known 指向 matrix 子域名并声明 LiveKit 通话")
    def _():
        body = expect(*c.request("GET", f"https://{domain}{PS}/.well-known/matrix/client"))
        assert body["m.homeserver"]["base_url"] == f"https://matrix.{domain}{PS}", body
        foci = body["org.matrix.msc4143.rtc_foci"]
        assert foci[0]["type"] == "livekit" and foci[0]["livekit_service_url"] == f"https://rtc.{domain}{PS}", foci
    _()

    @check("官网静态页（App 登录页链接的 Logo、条款、隐私政策）")
    def _():
        for path in ("/logo.png", "/terms", "/privacy", "/copyright"):
            status, _ = c.request("GET", f"https://{domain}{PS}{path}", raw=True)
            assert status == 200, f"{path} 返回 {status}"
    _()

    @check("客户端接口版本 /versions")
    def _():
        body = expect(*c.request("GET", c.hs("/_matrix/client/versions")))
        assert "v1.12" in body["versions"] or any(v >= "v1.11" for v in body["versions"]), body
    _()

    @check("联邦接口对外关闭")
    def _():
        for path in ("/_matrix/federation/v1/version", "/_matrix/key/v2/server"):
            status, _ = c.request("GET", c.hs(path), raw=True)
            assert status == 404, f"{path} 返回 {status}"
    _()

    @check("账号由 MAS 接管（auth_metadata + 动态注册客户端）")
    def _():
        body = expect(*c.request("GET", c.hs("/_matrix/client/v1/auth_metadata")))
        assert body["issuer"] == f"https://auth.{domain}{PS}/", body["issuer"]
        assert body.get("registration_endpoint"), "缺少 registration_endpoint，Element X 无法登录"
        assert "create" in body.get("prompt_values_supported", []), "MAS 未开放注册（prompt=create）"
    _()

    # 模拟 App 首次登录时的动态客户端注册，回调地址与 clients/*/prepare.py 生成的一致
    @check("MAS 接受安卓（正式/调试版）和 iOS 的客户端注册")
    def _():
        reverse = ".".join(reversed(domain.split(".")))
        apps = {"安卓正式版": f"{reverse}:/", "安卓调试版": f"{reverse}.debug:/", "iOS": f"{reverse}:/oauth/ios"}
        for name, redirect in apps.items():
            metadata = {
                "application_type": "native",
                "client_name": "smoke-test",
                "client_uri": f"https://{domain}{PS}",
                "logo_uri": f"https://{domain}{PS}/logo.png",
                "policy_uri": f"https://{domain}{PS}/privacy",
                "tos_uri": f"https://{domain}{PS}/terms",
                "redirect_uris": [redirect],
                "grant_types": ["authorization_code", "refresh_token",
                                "urn:ietf:params:oauth:grant-type:device_code"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            }
            status, body = c.request("POST", f"https://auth.{domain}{PS}/oauth2/registration", metadata)
            assert status == 201 and body.get("client_id"), f"{name}（{redirect}）被拒：HTTP {status} {body}"
    _()

    print("\n[2] 账号与登录")
    alice, bob, admin = f"alice{run_id}", f"bob{run_id}", f"admin{run_id}"

    @check("mas-cli 创建 3 个账号（含 1 个管理员）")
    def _():
        mas_cli("manage", "register-user", "--yes", "--ignore-password-complexity",
                "-p", password, "-e", f"{alice}@example.org", "-d", "Alice", alice)
        mas_cli("manage", "register-user", "--yes", "--ignore-password-complexity",
                "-p", password, "-e", f"{bob}@example.org", "-d", "Bob", bob)
        mas_cli("manage", "register-user", "--yes", "--ignore-password-complexity", "--admin",
                "-p", password, admin)
    _()

    tokens = {}

    @check("用户名 + 密码登录（经 Caddy 转给 MAS 兼容层）")
    def _():
        for user in (alice, bob):
            body = expect(*c.request("POST", c.hs("/_matrix/client/v3/login"), {
                "type": "m.login.password",
                "identifier": {"type": "m.id.user", "user": user},
                "password": password,
                "initial_device_display_name": "smoke-test",
            }))
            tokens[user] = body["access_token"]
            who = expect(*c.request("GET", c.hs("/_matrix/client/v3/account/whoami"), token=tokens[user]))
            assert who["user_id"] == f"@{user}:{domain}", who
    _()

    if len(tokens) < 2:
        return finish()
    ta, tb = tokens[alice], tokens[bob]
    uid_a, uid_b = f"@{alice}:{domain}", f"@{bob}:{domain}"

    print("\n[3] 私聊")
    dm = {}

    @check("Alice 发起私聊，Bob 接受邀请")
    def _():
        body = expect(*c.request("POST", c.hs("/_matrix/client/v3/createRoom"), {
            "is_direct": True, "preset": "trusted_private_chat", "invite": [uid_b],
        }, token=ta))
        dm["room"] = body["room_id"]
        expect(*c.request("POST", c.hs(f"/_matrix/client/v3/join/{urllib.parse.quote(dm['room'])}"), {}, token=tb))
    _()

    def send(token, room, content, event_type="m.room.message"):
        txn = secrets.token_hex(8)
        path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(room)}/send/{event_type}/{txn}"
        return expect(*c.request("PUT", c.hs(path), content, token=token))["event_id"]

    def wait_for_event(token, room, predicate, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(room)}/messages?dir=b&limit=30"
            body = expect(*c.request("GET", c.hs(path), token=token))
            for ev in body.get("chunk", []):
                if predicate(ev):
                    return ev
            time.sleep(1)
        raise AssertionError("超时没收到期望的消息")

    if "room" in dm:
        room = dm["room"]
        msg = {}

        @check("Alice 发消息，Bob 收到")
        def _():
            msg["id"] = send(ta, room, {"msgtype": "m.text", "body": f"你好 {run_id}"})
            wait_for_event(tb, room, lambda e: e["event_id"] == msg["id"] and e["content"]["body"] == f"你好 {run_id}")
        _()

        @check("Bob 回复、Alice 编辑、Bob 表情回应")
        def _():
            reply = send(tb, room, {"msgtype": "m.text", "body": "收到",
                                    "m.relates_to": {"m.in_reply_to": {"event_id": msg["id"]}}})
            edit = send(ta, room, {"msgtype": "m.text", "body": "* 改过", "m.new_content":
                                   {"msgtype": "m.text", "body": "改过"},
                                   "m.relates_to": {"rel_type": "m.replace", "event_id": msg["id"]}})
            react = send(tb, room, {"m.relates_to": {"rel_type": "m.annotation", "event_id": msg["id"], "key": "👍"}},
                         "m.reaction")
            for event_id, token in ((reply, ta), (edit, tb), (react, ta)):
                wait_for_event(token, room, lambda e, i=event_id: e["event_id"] == i)
        _()

        @check("撤回消息")
        def _():
            txn = secrets.token_hex(8)
            path = f"/_matrix/client/v3/rooms/{urllib.parse.quote(room)}/redact/{urllib.parse.quote(msg['id'])}/{txn}"
            expect(*c.request("PUT", c.hs(path), {"reason": "test"}, token=ta))
        _()

    print("\n[4] 群聊与搜索")

    @check("建公开群（带别名、进群目录），Bob 凭别名加入")
    def _():
        alias = f"group{run_id}"
        body = expect(*c.request("POST", c.hs("/_matrix/client/v3/createRoom"), {
            "preset": "public_chat", "room_alias_name": alias, "name": f"测试群 {run_id}", "visibility": "public",
        }, token=ta))
        expect(*c.request("POST", c.hs(f"/_matrix/client/v3/join/{urllib.parse.quote(f'#{alias}:{domain}')}"),
                          {}, token=tb))
        members = expect(*c.request("GET", c.hs(f"/_matrix/client/v3/rooms/{urllib.parse.quote(body['room_id'])}/joined_members"), token=ta))
        assert uid_b in members["joined"], members
        found = expect(*c.request("POST", c.hs("/_matrix/client/v3/publicRooms"),
                                  {"filter": {"generic_search_term": run_id}}, token=tb))
        assert any(r["room_id"] == body["room_id"] for r in found["chunk"]), found
    _()

    @check("按用户名搜到对方")
    def _():
        deadline = time.time() + 15
        while time.time() < deadline:
            body = expect(*c.request("POST", c.hs("/_matrix/client/v3/user_directory/search"),
                                     {"search_term": alice, "limit": 5}, token=tb))
            if any(r["user_id"] == uid_a for r in body["results"]):
                return
            time.sleep(1)
        raise AssertionError(body)
    _()

    @check("Sliding Sync（Element X 必需）能列出房间")
    def _():
        body = expect(*c.request("POST", c.hs("/_matrix/client/unstable/org.matrix.simplified_msc3575/sync"), {
            "lists": {"all": {"ranges": [[0, 20]], "required_state": [["m.room.name", ""]], "timeline_limit": 1}},
        }, token=ta))
        assert body["lists"]["all"]["count"] >= 2, body["lists"]
    _()

    @check("不能加入其他 Matrix 服务器的房间（联邦已关）")
    def _():
        # Synapse 按 federation_domain_whitelist 直接拒绝（日志里是 Federation denied），不会真的发请求
        start = time.time()
        status, body = c.request("POST", c.hs("/_matrix/client/v3/join/" + urllib.parse.quote("#matrix:matrix.org")),
                                 {}, token=ta)
        assert status >= 400 and time.time() - start < 3, f"HTTP {status}: {body}"
    _()

    print("\n[5] 媒体")

    @check("上传图片，对方下载内容一致")
    def _():
        blob = secrets.token_bytes(64 * 1024)
        status, body = c.request("POST", c.hs("/_matrix/media/v3/upload?filename=test.bin"), blob, token=ta,
                                 headers={"Content-Type": "application/octet-stream"})
        mxc = expect(status, body)["content_uri"]
        server, media_id = mxc[len("mxc://"):].split("/", 1)
        status, data = c.request("GET", c.hs(f"/_matrix/client/v1/media/download/{server}/{media_id}"),
                                 token=tb, raw=True)
        assert status == 200 and data == blob, f"HTTP {status}，长度 {len(data)}"
    _()

    print("\n[6] 音视频（MatrixRTC + LiveKit）")

    @check("服务端声明 LiveKit 传输（MSC4143）")
    def _():
        body = expect(*c.request("GET", c.hs("/_matrix/client/unstable/org.matrix.msc4143/rtc/transports"), token=ta))
        t = body["rtc_transports"][0]
        assert t["type"] == "livekit" and t["livekit_service_url"] == f"https://rtc.{domain}{PS}", body
    _()

    @check("用 OpenID 换通话令牌，LiveKit 接受该令牌")
    def _():
        room = dm.get("room")
        assert room, "缺少私聊房间"
        openid = expect(*c.request("POST", c.hs(f"/_matrix/client/v3/user/{urllib.parse.quote(uid_a)}/openid/request_token"),
                                   {}, token=ta))
        body = expect(*c.request("POST", f"https://rtc.{domain}{PS}/sfu/get", {
            "room": room, "openid_token": openid, "device_id": "SMOKETEST",
        }))
        assert body["url"] == f"wss://rtc.{domain}{PS}", body
        claims = jwt_payload(body["jwt"])
        assert claims["video"]["roomJoin"] is True, claims
        status, raw = c.request("GET", f"https://rtc.{domain}{PS}/rtc/validate?access_token={body['jwt']}", raw=True)
        assert status == 200, f"LiveKit 校验返回 {status}: {raw[:200]!r}"
    _()

    @check("不在房间里的人拿不到该房间的通话令牌")
    def _():
        outsider = f"eve{run_id}"
        mas_cli("manage", "register-user", "--yes", "--ignore-password-complexity", "-p", password, outsider)
        tok = expect(*c.request("POST", c.hs("/_matrix/client/v3/login"), {
            "type": "m.login.password", "identifier": {"type": "m.id.user", "user": outsider}, "password": password,
        }))["access_token"]
        openid = expect(*c.request("POST", c.hs(f"/_matrix/client/v3/user/{urllib.parse.quote(f'@{outsider}:{domain}')}/openid/request_token"),
                                   {}, token=tok))
        status, body = c.request("POST", f"https://rtc.{domain}{PS}/sfu/get", {
            "room": dm["room"], "openid_token": openid, "device_id": "EVE",
        })
        assert status in (401, 403), f"应拒绝，实际 HTTP {status}: {body}"
    _()

    print("\n[7] 推送")

    @check("ntfy 推送服务在线，并作为 UnifiedPush 的 Matrix 网关")
    def _():
        body = expect(*c.request("GET", f"https://push.{domain}{PS}/v1/health"))
        assert body.get("healthy") is True, body
        body = expect(*c.request("GET", f"https://push.{domain}{PS}/_matrix/push/v1/notify"))
        assert body == {"unifiedpush": {"gateway": "matrix"}}, body
    _()

    print("\n[8] 后台")

    @check("管理员令牌可调用 Synapse 管理接口，普通用户不行")
    def _():
        out = mas_cli("manage", "issue-compatibility-token", "--yes-i-want-to-grant-synapse-admin-privileges", admin)
        token = next(w for w in out.split() if w.startswith("mct_"))
        body = expect(*c.request("GET", c.hs(f"/_synapse/admin/v2/users?guests=false&name={run_id}"), token=token))
        names = {u["name"] for u in body["users"]}
        assert {uid_a, uid_b} <= names, names
        status, _ = c.request("GET", c.hs("/_synapse/admin/v2/users?guests=false"), token=ta)
        assert status == 403, f"普通用户访问管理接口返回 {status}"
    _()

    @check("MAS 管理接口已开放（后台管理账号用）")
    def _():
        status, body = c.request("GET", f"https://auth.{domain}{PS}/api/admin/v1/users")
        assert status in (400, 401) and "authorization" in json.dumps(body).lower(), f"HTTP {status}: {body}"
    _()

    @check("后台网页可打开")
    def _():
        status, html = c.request("GET", f"https://admin.{domain}{PS}/", raw=True)
        assert status == 200 and b"<html" in html.lower(), status
    _()

    return finish()


def finish():
    failed = [r for r in results if not r[1]]
    print(f"\n共 {len(results)} 项，通过 {len(results) - len(failed)}，失败 {len(failed)}")
    for name, _, why in failed:
        print(f"  - {name}: {why}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
