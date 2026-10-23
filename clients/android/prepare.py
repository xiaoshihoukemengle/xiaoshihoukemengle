#!/usr/bin/env python3
"""拉取 Element X Android 上游源码并改成我们的 App。

    python3 prepare.py            # 生成到 clients/android/build/element-x-android
    python3 prepare.py --check    # 只检查改动点在上游里还在不在（升级上游版本时先跑这个）

每一处改动都按“原文 -> 新文”精确替换，原文找不到或出现多次就直接报错，
这样升级上游版本时不会悄悄漏改。品牌和服务器配置在 ../brand.env。
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSTREAM_REPO = "https://github.com/element-hq/element-x-android"
UPSTREAM_TAG = (HERE / "UPSTREAM_TAG").read_text().strip()
SRC = HERE / "build" / "element-x-android"


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
        sys.exit("BRAND_COLOR 要写 8 位 ARGB 十六进制，比如 FF2F6BFF")
    brand["DOMAIN_REVERSED"] = ".".join(reversed(brand["DOMAIN"].split(".")))
    return brand


def edits(b):
    """(文件, 原文, 新文) 列表。"""
    d = b["DOMAIN"]
    site = f"https://{d}"
    enterprise = "features/enterprise/impl-foss/src/main/kotlin/io/element/android/features/enterprise/impl/DefaultEnterpriseService.kt"
    return [
        # ---- 应用名、包名、OAuth 客户端信息（MAS 要求这些地址与回调 scheme 同属一个域名）----
        ("plugins/src/main/kotlin/config/BuildTimeConfig.kt",
         'const val APPLICATION_ID = "io.element.android.x"',
         f'const val APPLICATION_ID = "{b["APP_ID"]}"'),
        ("plugins/src/main/kotlin/config/BuildTimeConfig.kt",
         'const val APPLICATION_NAME = "Element X"',
         f'const val APPLICATION_NAME = "{b["APP_NAME"]}"'),
        ("plugins/src/main/kotlin/config/BuildTimeConfig.kt",
         "val METADATA_HOST_REVERSED: String? = null",
         f'val METADATA_HOST_REVERSED: String? = "{b["DOMAIN_REVERSED"]}"'),
        ("plugins/src/main/kotlin/config/BuildTimeConfig.kt",
         "val URL_WEBSITE: String? = null", f'val URL_WEBSITE: String? = "{site}"'),
        ("plugins/src/main/kotlin/config/BuildTimeConfig.kt",
         "val URL_LOGO: String? = null", f'val URL_LOGO: String? = "{site}/logo.png"'),
        ("plugins/src/main/kotlin/config/BuildTimeConfig.kt",
         "val URL_COPYRIGHT: String? = null", f'val URL_COPYRIGHT: String? = "{site}/copyright"'),
        ("plugins/src/main/kotlin/config/BuildTimeConfig.kt",
         "val URL_ACCEPTABLE_USE: String? = null", f'val URL_ACCEPTABLE_USE: String? = "{site}/terms"'),
        ("plugins/src/main/kotlin/config/BuildTimeConfig.kt",
         "val URL_PRIVACY: String? = null", f'val URL_PRIVACY: String? = "{site}/privacy"'),
        ("plugins/src/main/kotlin/config/BuildTimeConfig.kt",
         "val URL_POLICY: String? = null", f'val URL_POLICY: String? = "{site}/privacy"'),
        # ---- 不带谷歌 FCM（安卓推送走自建 ntfy / UnifiedPush）----
        ("plugins/src/main/kotlin/config/BuildTimeConfig.kt",
         "const val PUSH_CONFIG_INCLUDE_FIREBASE: Boolean = true",
         "const val PUSH_CONFIG_INCLUDE_FIREBASE: Boolean = false"),
        # ---- 去掉 PostHog / Sentry 统计，整个模块不打包 ----
        ("plugins/src/main/kotlin/ModulesConfig.kt",
         '''        println("Analytics enabled with Posthog and Sentry")
        AnalyticsConfig.Enabled(
            withPosthog = true,
            withSentry = true,
        )''',
         '''        println("Analytics disabled")
        AnalyticsConfig.Disabled'''),
        # ---- 界面里提到的产品名 ----
        ("appconfig/src/main/kotlin/io/element/android/appconfig/ApplicationConfig.kt",
         'const val PRODUCTION_APPLICATION_NAME: String = "Element"',
         f'const val PRODUCTION_APPLICATION_NAME: String = "{b["APP_NAME"]}"'),
        ("appconfig/src/main/kotlin/io/element/android/appconfig/ApplicationConfig.kt",
         'const val DESKTOP_APPLICATION_NAME: String = "Element"',
         f'const val DESKTOP_APPLICATION_NAME: String = "{b["APP_NAME"]}"'),
        # ---- 默认推送网关：自建 ntfy，不用 unifiedpush.org ----
        ("libraries/pushproviders/unifiedpush/src/main/kotlin/io/element/android/libraries/pushproviders/unifiedpush/UnifiedPushConfig.kt",
         'const val DEFAULT_PUSH_GATEWAY_HTTP_URL: String = "https://matrix.gateway.unifiedpush.org/_matrix/push/v1/notify"',
         f'const val DEFAULT_PUSH_GATEWAY_HTTP_URL: String = "https://push.{d}/_matrix/push/v1/notify"'),
        # ---- 只连我们自己的服务器（上游给企业版留的扩展点）----
        (enterprise,
         "override fun accountProviderAllowList(): List<AccountProvider> = emptyList()",
         f'override fun accountProviderAllowList(): List<AccountProvider> = listOf(AccountProvider.Generic(serverName = "{d}"))'),
        (enterprise,
         "override fun canConnectToAnyAccountProvider(): Boolean = true",
         "override fun canConnectToAnyAccountProvider(): Boolean = false"),
        (enterprise,
         "override suspend fun isAllowedToConnectToAccountProvider(accountProvider: AccountProvider) = true",
         "override suspend fun isAllowedToConnectToAccountProvider(accountProvider: AccountProvider) =\n"
         "        accountProviderAllowList().any { it.matches(accountProvider) }"),
        # 不去服务器查 Element Pro 的配置文件
        (enterprise,
         "override suspend fun isElementProEnforced(serverName: String): Boolean = withContext(dispatchers.io) {",
         "override suspend fun isElementProEnforced(serverName: String): Boolean = false\n\n"
         "    @Suppress(\"unused\")\n"
         "    private suspend fun upstreamIsElementProEnforced(serverName: String): Boolean = withContext(dispatchers.io) {"),
        (enterprise,
         "override fun unifiedPushDefaultPushGateway(): String? = null",
         f'override fun unifiedPushDefaultPushGateway(): String? = "https://push.{d}/_matrix/push/v1/notify"'),
        # 不往 Element 的服务器上传问题报告
        (enterprise,
         "        return flowOf(BugReportUrl.UseDefault)",
         "        return flowOf(BugReportUrl.Disabled)"),
        # 主色
        (enterprise,
         '''    override fun brandColorsFlow(sessionId: SessionId?): Flow<Color?> {
        return flowOf(null)''',
         f'''    override fun brandColorsFlow(sessionId: SessionId?): Flow<Color?> {{
        return flowOf(Color(0x{b["BRAND_COLOR"].upper()}))'''),
    ]


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


ICON_FOREGROUND = """<?xml version="1.0" encoding="utf-8"?>
<!-- 临时图标：对话气泡。正式图标定了再换 -->
<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:width="108dp" android:height="108dp"
    android:viewportWidth="108" android:viewportHeight="108">
    <path android:fillColor="#FFFFFF"
        android:pathData="M54,30C40.7,30 30,39.4 30,51C30,57.6 33.5,63.5 39,67.3L37,78L48.3,71.4C50.1,71.8 52,72 54,72C67.3,72 78,62.6 78,51C78,39.4 67.3,30 54,30Z" />
</vector>
"""

ICON_MONOCHROME = ICON_FOREGROUND.replace("#FFFFFF", "#000000")

ADAPTIVE_ICON = """<?xml version="1.0" encoding="utf-8"?>
<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@drawable/ic_launcher_background" />
    <foreground android:drawable="@drawable/ic_launcher_foreground_vector" />
    <monochrome android:drawable="@drawable/ic_launcher_monochrome_vector" />
</adaptive-icon>
"""

ICON_BACKGROUND = """<?xml version="1.0" encoding="utf-8"?>
<shape xmlns:android="http://schemas.android.com/apk/res/android" android:shape="rectangle">
    <solid android:color="#{color}" />
</shape>
"""


def replace_icon(root, brand):
    """换成临时图标：安卓 8+ 用矢量自适应图标，更老的系统用生成的 PNG。"""
    res_root = root / "appicon/element/src"
    color = brand["BRAND_COLOR"][2:]
    for variant in ("debug", "release", "nightly"):
        (res_root / variant / "res/drawable/ic_launcher_background.xml").write_text(ICON_BACKGROUND.format(color=color))
    main = res_root / "main/res"
    (main / "drawable").mkdir(exist_ok=True)
    (main / "drawable/ic_launcher_foreground_vector.xml").write_text(ICON_FOREGROUND)
    (main / "drawable/ic_launcher_monochrome_vector.xml").write_text(ICON_MONOCHROME)
    for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
        (main / "mipmap-anydpi-v26" / name).write_text(ADAPTIVE_ICON)
    sizes = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
    for density, px in sizes.items():
        folder = main / f"mipmap-{density}"
        for old in folder.glob("ic_launcher*.webp"):
            old.unlink()
        draw_icon(folder / "ic_launcher.png", px, brand["BRAND_COLOR"], "square")
        draw_icon(folder / "ic_launcher_round.png", px, brand["BRAND_COLOR"], "round")
        # 自适应图标的图层是 108dp，图标预览页（IconPreview.kt）引用这两张
        layer_px = px * 108 // 48
        draw_icon(folder / "ic_launcher_foreground.png", layer_px, brand["BRAND_COLOR"], "foreground")
        draw_icon(folder / "ic_launcher_monochrome.png", layer_px, brand["BRAND_COLOR"], "monochrome")
    playstore = res_root / "main/ic_launcher-playstore.png"
    draw_icon(playstore, 512, brand["BRAND_COLOR"], "square")


def draw_icon(path, px, argb, kind):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        sys.exit("生成临时图标需要 Pillow：pip3 install pillow")

    size = px * 4
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgb = tuple(int(argb[i:i + 2], 16) for i in (2, 4, 6))
    if kind == "round":
        d.ellipse([0, 0, size - 1, size - 1], fill=rgb)
    elif kind == "square":
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=size // 5, fill=rgb)
    bubble = "black" if kind == "monochrome" else "white"
    # 气泡：椭圆 + 小尾巴，与矢量前景同一造型（108 网格换算）
    u = size / 108
    d.ellipse([22 * u, 26 * u, 86 * u, 76 * u], fill=bubble)
    d.polygon([(36 * u, 64 * u), (32 * u, 86 * u), (52 * u, 72 * u)], fill=bubble)
    img.resize((px, px), Image.LANCZOS).save(path)


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
    subprocess.run(["git", "clone", "-q", "--depth", "1", "--branch", UPSTREAM_TAG, UPSTREAM_REPO, str(SRC)], check=True)


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
    if args.check:
        print(f"上游 {UPSTREAM_TAG}：{len(edits(brand))} 处改动点全部能对上")
        return
    replace_icon(SRC, brand)
    print(f"已生成 {SRC}（上游 {UPSTREAM_TAG}，{len(edits(brand))} 处改动 + 临时图标）")
    print("编译：cd build/element-x-android && ./gradlew :app:assembleFdroidDebug")


if __name__ == "__main__":
    main()
