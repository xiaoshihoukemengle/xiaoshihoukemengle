#!/usr/bin/env python3
"""拉取 Element X iOS 上游源码并改成我们的 App（需要在 Mac 上编译）。

    python3 prepare.py            # 生成到 clients/ios/build/element-x-ios
    python3 prepare.py --check    # 只检查改动点在上游里还在不在

和安卓一样按“原文 -> 新文”精确替换，对不上就报错。品牌和服务器配置在 ../brand.env。
生成后：cd build/element-x-ios && xcodegen && open ElementX.xcodeproj
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSTREAM_REPO = "https://github.com/element-hq/element-x-ios"
UPSTREAM_TAG = (HERE / "UPSTREAM_TAG").read_text().strip()
SRC = HERE / "build" / "element-x-ios"


def load_brand():
    brand = {}
    for line in (HERE.parent / "brand.env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            brand[key.strip()] = value.strip()
    for key in ("APP_NAME", "DOMAIN", "APP_ID", "BRAND_COLOR"):
        if not brand.get(key):
            sys.exit(f"brand.env 缺少 {key}")
    if not re.fullmatch(r"[0-9A-Fa-f]{8}", brand["BRAND_COLOR"]):
        sys.exit("BRAND_COLOR 要写 8 位 ARGB 十六进制")
    # 环境变量优先：CI 在构建时按服务器地址填入，地址不进代码仓库
    for key in ("DOMAIN", "PUBLIC_PORT"):
        if os.environ.get(key):
            brand[key] = os.environ[key]
    port = brand.get("PUBLIC_PORT", "")
    brand["PORT_SUFFIX"] = "" if port in ("", "443") else ":" + port
    brand["DOMAIN_REVERSED"] = ".".join(reversed(brand["DOMAIN"].split(".")))
    return brand


def edits(b):
    d = b["DOMAIN"]
    ps = b["PORT_SUFFIX"]
    site = f"https://{d}{ps}"
    settings = "ElementX/Sources/Application/Settings/AppSettings.swift"
    result = [
        # ---- 名称、Bundle ID、App Group ----
        ("app.yml", "APP_DISPLAY_NAME: Element X", f"APP_DISPLAY_NAME: {b['APP_NAME']}"),
        ("app.yml", "PRODUCTION_APP_NAME: Element", f"PRODUCTION_APP_NAME: {b['APP_NAME']}"),
        ("app.yml", "APP_GROUP_IDENTIFIER: group.io.element", f"APP_GROUP_IDENTIFIER: group.{b['APP_ID']}"),
        ("app.yml", "BASE_BUNDLE_IDENTIFIER: io.element.elementx", f"BASE_BUNDLE_IDENTIFIER: {b['APP_ID']}"),
        # ---- 只连我们自己的服务器 ----
        (settings,
         'private(set) var accountProviders: [AccountProvider] = [.managed(serverName: "matrix.org", baseURL: "https://matrix-client.matrix.org")]',
         f'private(set) var accountProviders: [AccountProvider] = [.managed(serverName: "{d}", baseURL: "https://matrix.{d}{ps}")]'),
        (settings, "private(set) var allowOtherAccountProviders = true",
         "private(set) var allowOtherAccountProviders = false"),
        # ---- OAuth 客户端信息，MAS 要求与回调同属一个域名 ----
        (settings, 'private(set) var websiteURL: URL = "https://element.io"',
         f'private(set) var websiteURL: URL = "{site}"'),
        (settings, 'private(set) var logoURL: URL = "https://element.io/mobile-icon.png"',
         f'private(set) var logoURL: URL = "{site}/logo.png"'),
        (settings, 'private(set) var copyrightURL: URL = "https://element.io/copyright"',
         f'private(set) var copyrightURL: URL = "{site}/copyright"'),
        (settings, 'private(set) var acceptableUseURL: URL = "https://element.io/acceptable-use-policy-terms"',
         f'private(set) var acceptableUseURL: URL = "{site}/terms"'),
        (settings, 'private(set) var privacyURL: URL = "https://element.io/privacy"',
         f'private(set) var privacyURL: URL = "{site}/privacy"'),
        # 登录回调用自定义 scheme（域名倒写），不依赖 Associated Domains：
        # 超级签每个账号的 Team ID 不同，https 回调要为每个账号维护 apple-app-site-association
        (settings,
         'private(set) nonisolated(unsafe) var oAuthRedirectURL: URL! = URL(string: "https://element.io/oauth/ios/\\(InfoPlistReader.main.bundleIdentifier)")',
         f'private(set) nonisolated(unsafe) var oAuthRedirectURL: URL! = URL(string: "{b["DOMAIN_REVERSED"]}:/oauth/ios")'),
        # ---- 推送网关（iOS 走 Sygnal → APNs，阶段 3 部署）----
        (settings, 'private(set) var pushGatewayBaseURL: URL = "https://matrix.org"',
         f'private(set) var pushGatewayBaseURL: URL = "https://apns.{d}"'),
        # ---- 去掉 Element Call 内置的 PostHog / Sentry 上报地址 ----
        (settings, 'let elementCallPosthogAPIHost = "https://posthog-element-call.element.io"',
         'let elementCallPosthogAPIHost = ""'),
        (settings, 'let elementCallPosthogAPIKey = "phc_rXGHx9vDmyEvyRxPziYtdVIv0ahEv8A9uLWFcCi1WcU"',
         'let elementCallPosthogAPIKey = ""'),
        (settings, 'let elementCallPosthogSentryDSN = "https://3bd2f95ba5554d4497da7153b552ffb5@sentry.tools.element.io/41"',
         'let elementCallPosthogSentryDSN = ""'),
        (settings, 'private(set) var analyticsTermsURL: URL? = "https://element.io/cookie-policy"',
         "private(set) var analyticsTermsURL: URL? = nil"),
        # ---- App 本体的统计、崩溃上报、问题反馈和地图：全部关掉，不连任何第三方 ----
        # 上游这个文件是占位值（*.localhost），官方构建时才注入真实密钥；这里统一改成 nil
        *[("Components/Secrets/Secrets.swift", f"    static let {name}: String? = \"{value}\"",
           f"    static let {name}: String? = nil") for name, value in (
            ("sentryDSN", "https://username@sentry.localhost/project_id"),
            ("sentryRustDSN", "https://username@sentry.localhost/project_id"),
            ("postHogHost", "https://posthog.localhost"),
            ("postHogAPIKey", "your_key"),
            ("rageshakeURL", "https://rageshake.localhost/submit"),
            ("mapLibreAPIKey", "your_key"))],
        # ---- 关联域名改成我们的 ----
        ("ElementX/SupportingFiles/target.yml",
         """        - applinks:element.io
        - applinks:app.element.io
        - applinks:staging.element.io
        - applinks:develop.element.io
        - applinks:mobile.element.io
        - applinks:matrix.to
""",
         f"""        - applinks:{d}
"""),
        ("ElementX/SupportingFiles/target.yml", "        - webcredentials:*.element.io",
         f"        - webcredentials:{d}"),
    ]
    if b.get("IOS_TEAM_ID"):
        result.append(("app.yml", "DEVELOPMENT_TEAM: 7J4U792NQT", f"DEVELOPMENT_TEAM: {b['IOS_TEAM_ID']}"))
    return result


def apply_edits(root, brand, dry_run):
    problems = []
    for rel, old, new in edits(brand):
        path = root / rel
        if not path.exists():
            problems.append(f"{rel}: 文件不存在")
            continue
        text = path.read_text()
        count = text.count(old)
        if count != 1:
            problems.append(f"{rel}: 原文出现 {count} 次（应为 1）：{old.splitlines()[0][:80]}")
            continue
        if not dry_run:
            path.write_text(text.replace(old, new))
    return problems


def fetch_upstream():
    if SRC.exists():
        current = subprocess.run(["git", "describe", "--tags", "--exact-match"], cwd=SRC,
                                 capture_output=True, text=True).stdout.strip()
        if current == UPSTREAM_TAG:
            subprocess.run(["git", "reset", "-q", "--hard"], cwd=SRC, check=True)
            subprocess.run(["git", "clean", "-qfd"], cwd=SRC, check=True)
            return
        shutil.rmtree(SRC)
    SRC.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "advice.detachedHead=false", "clone", "-q", "--depth", "1",
                    "--branch", UPSTREAM_TAG, UPSTREAM_REPO, str(SRC)], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="只检查，不改文件")
    args = parser.parse_args()

    brand = load_brand()
    fetch_upstream()
    problems = apply_edits(SRC, brand, dry_run=args.check)
    if problems:
        print("以下改动点在上游 " + UPSTREAM_TAG + " 里对不上，需要人工处理：")
        for p in problems:
            print("  - " + p)
        sys.exit(1)
    print(f"上游 {UPSTREAM_TAG}：{len(edits(brand))} 处改动点" + ("全部能对上" if args.check else "已应用"))
    if not args.check:
        print("下一步：cd build/element-x-ios && xcodegen && open ElementX.xcodeproj")


if __name__ == "__main__":
    main()
