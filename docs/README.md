# 聊天软件（Matrix 方案）

手机聊天应用（安卓 + iOS），服务全部自建。完整方案、版本选型和分阶段计划见 [方案文档](https://claude.ai/artifact/6VAGgwxscsVw5eJRWrNgfR)。

## 组成

| 部分 | 基于 | 目录 |
| --- | --- | --- |
| 服务端 | Synapse + MAS + LiveKit + ntfy + Ketesa，Docker Compose 部署 | [deploy/](../deploy/) |
| 安卓 App | Element X Android 改品牌 | [clients/android/](../clients/) |
| iOS App | Element X iOS 改品牌，超级签分发 | [clients/ios/](../clients/) |

## 已定的要求

- 功能尽量对齐 Telegram；所有数据和素材自托管，不接任何第三方服务（iOS 推送只能走 APNs，推送里不带消息内容）。
- 注册登录：邮箱 + 用户名 + 密码，手机号可选（后续自研）。
- 联邦关闭，只做自己的平台。
- 开源许可：服务端和客户端上游都是 AGPL-3.0，改过的代码需要开源。

## 验收

每个阶段都要能在干净环境里跑通自动化测试，服务端见 `deploy/tests/`。
