# 上游来源

本目录导入自 [teamgram/teamgram-server](https://github.com/teamgram/teamgram-server)，许可证 Apache 2.0（见 `LICENSE`）。

| 项 | 值 |
| --- | --- |
| 上游提交 | `708fb9536f60e15d9bf4f1c302aa4251bfefab19`（2026-08-04） |
| 兼容 API layer | 228 |
| 导入日期 | 2026-10-23 |

导入时没有修改任何上游文件。之后我们自己的改动都单独提交，提交说明里写清楚动了哪些上游文件，方便以后合并上游更新。

## 导入时的状态

- `go build ./...`：通过（Go 1.24）。
- `go test ./...`：11 个包通过，8 个包失败。失败全部来自上游本身，与导入无关：
  - 5 个包的测试编译不过：`gnetway/internal/server/gnet`、`httpserver/internal/dao`、`dfs/internal/dao/examples/download`、`dfs/internal/dao/examples/upload`、`dfs/internal/ffmpegutil`
  - `pkg/goffmpeg/tests` 依赖本机 `/tmp/ffmpeg/` 下的样例文件
  - `dfs/internal/imaging/jpeg` 的 `TestDecodeProgressive`、`TestDecodeEOF` 失败
  - `bff/users/internal/core` 的 `TestPatchBotUsernameFromImmutableAddsUsername` 失败

这些会在后续单独修复。
