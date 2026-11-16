# 双实例发布：准备和旧请求收尾不阻塞用户

常规更新不再先全站排空。旧实例继续接请求，新实例在另一个本地端口完成准备后，通过 Caddy graceful reload 切换 API 和静态页面。新请求立即进入新实例；旧连接继续由旧实例处理，收尾后才停止旧实例。

入口切换目标为秒级，不等于整个构建、升级、校验和旧请求收尾都能瞬间结束。操作过程不自动重提生成，不改变 Key、价格或账务策略。

## 发布前提

- 使用干净、已推送且已由服务器 Git 拉取的提交；前端从同一提交本地构建，`web/dist/.build-commit` 写入完整 SHA。
- 主机必须有容纳两个 API 实例的内存与端口；当前切换工具针对每槽位一个 Uvicorn 进程，不适用于单端口下混合多个版本或多个进程 ID 的负载均衡。
- 两个实例使用同一业务数据库、会话/加密配置和媒体存储。后台查询沿用数据库抢占与幂等结算，不重新提交已有视频。
- 每个实例必须通过进程环境分别指定 `DEPLOYMENT_DRAIN_FILE`，例如私有运行目录下的 `blue-draining` 和 `green-draining`。不能继承同一个共享暂停标记。
- 两个生产实例都设置 `STARTUP_MIGRATIONS_ENABLED=false`。此时启动只校验映射表和列，不自动执行 DDL、历史数据迁移、初始化管理员或重写模型别名。缺表/列会拒绝启动。
- 外层停止预算仍遵守 [优雅退出说明](graceful-deployment.md)。不要用进程管理器的短等待强杀旧实例。

## 数据库准备是独立步骤

数据库结构不变时，仅检查：

```sh
python scripts/migrate.py --check
```

如果存在升级，先备份，在隔离副本演练，并审核新旧版本可同时运行的兼容性。仅确认安全后执行：

```sh
python scripts/migrate.py --apply
```

这条命令不会判断业务兼容性，也不意味着所有现有迁移都可在线执行。字段删除、重命名、数据重写、长时间持锁等不能直接热切换；需要拆成兼容的增量步骤，或另行安排维护。不要为了“零停机”绕过这一检查。

## 一次发布的操作顺序

1. 旧实例正常服务。完成 Git 拉取、前端构建与上传、备份和必要数据库准备。
2. 在备用端口启动候选实例。只更新备用 Supervisor program，不对正在服务的 program 执行 `update/restart`。
3. 预热并检查候选 `/health`、`/api/health/ready`、模型目录与需要验证的只读接口。readiness 应为 200，`release` 匹配 SHA，`startup_migrations=false`。不要用付费生成充当健康探针。
4. 检查 Caddy 实际用户能读取所有公开构建文件。公开静态目录通常为 755、文件 644；不要扩大 `.env` 或密钥权限。所有运行文件和构建目录必须被 Git 忽略且未被跟踪。
5. 准备私有的候选 Caddyfile，同时把 API 上游指向备用端口、静态根目录指向候选 `web/dist`。保留现有 TLS、接口路径、归档服务和安全设置。不要添加全站 503，也不要停止 Caddy。
6. 运行下方切换工具。它会验证候选 Git/构建版本、Web 用户权限、候选 readiness 和 Caddy 配置；只有全部通过才替换配置并 reload。
7. 验证公开 readiness 的版本和实例 ID，以及首页与入口 JS/CSS。验证失败时恢复旧路由，保留两个进程，避免截断任何一边已受理的请求。
8. 验证成功后，新版本继续正常受理。再单独优雅停止旧 program，允许其现有 HTTP/SSE 和后台文本流在原期限内结束；不要等全平台所有 `processing` 视频变成零，因为新版本已经可以接管这些持久化任务的查询。
9. 保留旧发布目录供回退。旧槽位停止后才调整它的配置或取消其开机自启；不要为修改启动选项而再次重启活动槽位。

示意配置（端口和路径均需按部署环境替换，实际主机配置不提交）：

```ini
environment=STARTUP_MIGRATIONS_ENABLED="false",DEPLOYMENT_DRAIN_FILE="/srv/cat-api/runtime/green-draining"
# command 中的 uvicorn 使用独立端口与原有退出预算：
# --host 127.0.0.1 --port 9001 --timeout-graceful-shutdown 660
stopsignal=TERM
stopwaitsecs=1350
```

```caddyfile
# 仅展示需要切换的两处；不是完整站点配置。
root * /srv/cat-api/releases/COMMIT/web/dist
reverse_proxy 127.0.0.1:9001 {
    stream_close_delay 660s
}
```

## 可重复使用的切换工具

```sh
python scripts/switch_release.py \
  --root /srv/cat-api/releases/COMMIT \
  --commit FULL_GIT_SHA \
  --candidate-url http://127.0.0.1:9001 \
  --public-url https://api.example.com \
  --candidate-config /srv/cat-api/private/candidate.caddy \
  --active-config /etc/caddy/Caddyfile \
  --state-dir /srv/cat-api/private/switch-state \
  --web-user caddy
```

候选 checkout 必须匹配已 fetch 的 `origin/main`；切换前仍需遵守项目的 Git 推送/拉取流程。`state-dir` 应为所有发布共享的私有目录，用于锁、回退配置和日志，不可提交 Git。工具不会创建/停止 Supervisor program，也不会启停排空开关、执行迁移或调用模型。仅显示成功 SHA 不足以证明路由切换：它同时检查独立的实例 ID，因此配置更新即使沿用同一提交也能验证切到了新进程。

切换验证成功后，Caddy 命令可能仍在等待旧连接释放；这期间新请求已由新实例受理。不要把等待收尾误判为平台停摆，也不要因此强杀旧进程。退出异常时检查日志并保留两个实例，不要盲目执行第二次生成。

## 本地验证

`test/test_blue_green.py` 使用两个隔离 HTTP 实例和真实 Caddy 验证：旧 SSE 未完成时新请求立即成功、候选不可用不切换，以及页面异常时回退。另启动两个共享隔离数据库的真实 Cat API 进程，确认旧流完整结束、新实例能接新生成、重复请求不再次调用供应商，每个任务只计费一次。提供官方 Caddy 测试二进制路径：

```sh
CADDY_TEST_BINARY=/path/to/caddy python -m pytest test/test_blue_green.py -o addopts='' -q
```

测试不调用真实供应商，不连接生产数据库。进程退出的其他边界仍由现有停机回归覆盖。
