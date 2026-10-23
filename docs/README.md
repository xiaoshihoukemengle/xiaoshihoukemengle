# 聊天软件项目说明

目标：做一款功能和界面接近 Telegram 的手机聊天应用（安卓 + iOS），服务全部自建，全球可用，并配一个强大、细致、结构清晰的后台管理系统。

调研和选型文档：[聊天软件技术选型调研](https://claude.ai/artifact/PGRzYyFsftvQJSeAfmWqxn)

## 技术路线

| 部分 | 方案 | 语言 | 许可证 |
| --- | --- | --- | --- |
| 服务端 | `server/`：基于 Teamgram Server，兼容 TG API layer 228 | Go | Apache 2.0 |
| 安卓 App | 基于 teamgram-android（TG 官方安卓客户端），换名换图标 | Java | GPL v2+，需开源 |
| iOS App | 基于 teamgram-ios（TG 官方 iOS 客户端），换名换图标，超级签分发 | Swift | GPL v2+，需开源 |
| 后台管理 | 自研：Go 管理 API + Vue 3 前端 | Go / TypeScript | 自有 |
| 基础设施 | MySQL、Redis、etcd、Kafka、MinIO、FFmpeg，全部自建 | — | — |

## 已确定的要求

- 功能对齐 Telegram；Teamgram 开源版没有的功能，自己用 Go 开发（不买企业版）。
- 不使用任何第三方云服务。iOS 离线推送只能走 APNs，推送里只放“有新消息”信号，不放内容。
- 登录用邮箱 + 用户名，手机号可选；短信走自有网关。
- iOS 用超级签分发：服务端要为每个签名账号保存 APNs 密钥，并按设备所属账号路由推送。
- App 按 GPL 开源；服务端和后台可以闭源。

## 目录

| 目录 | 内容 |
| --- | --- |
| `server/` | 服务端（Teamgram 导入版，来源见 `server/UPSTREAM.md`） |
| `docs/` | 项目文档、开发计划 |

开发计划见 [roadmap.md](roadmap.md)。
