# 手机 App

两端都基于 Element X（AGPL-3.0），不 fork 整个仓库，而是用脚本拉取固定的上游版本，再按“原文 → 新文”精确改几处配置。上游改了对应代码时脚本会直接报错，不会悄悄改错地方。升级上游只需改 `UPSTREAM_TAG` 后重跑脚本。

| | 上游版本 | 脚本 |
| --- | --- | --- |
| 安卓 | `android/UPSTREAM_TAG` | `python3 android/prepare.py` |
| iOS | `ios/UPSTREAM_TAG` | `python3 ios/prepare.py` |

名称、域名、包名、主色统一写在 [brand.env](brand.env)，现在都是临时值，Logo 也是临时生成的。

## 改了什么

- 只能连我们自己的服务器（`brand.env` 的 DOMAIN），不显示 matrix.org 等其他服务器。
- 注册登录走服务端的 MAS 网页（邮箱 + 用户名 + 密码）。登录回调用域名倒写的自定义 scheme（如 `test.chat:/`），服务端测试里已模拟两端的客户端注册。
- 去掉统计、崩溃上报和 Element 的推送服务。安卓默认用自建 ntfy（UnifiedPush）；iOS 推送网关暂指向 `apns.域名`，Sygnal 等拿到超级签账号的 APNs 密钥后部署。
- App 里的官网、条款、隐私链接指向 `https://域名/...`，页面在 `deploy/site/`。

## 编译

安卓（JDK 21 + Android SDK，compileSdk 37）：

```sh
python3 android/prepare.py
cd android/build/element-x-android && ./gradlew :app:assembleFdroidDebug
# 安装包在 app/build/outputs/apk/fdroid/debug/
```

iOS（Xcode + xcodegen，`brew install xcodegen`）：

```sh
python3 ios/prepare.py
cd ios/build/element-x-ios && xcodegen && open ElementX.xcodeproj
```

模拟器连本地开发服务器时，要把 `deploy/README.md` 里列的几个域名指向本机，并在模拟器里信任 Caddy 的根证书。
