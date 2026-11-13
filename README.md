# Cat API

独立的模型 API 平台。工作台通过 HTTPS 和 API Key 调用平台。

## 本地运行

可重复查看的 API Key 使用 `API_KEY_ENCRYPTION_KEY` 加密保存。该值是通过 `cryptography.fernet.Fernet.generate_key()` 生成的持久密钥，填写在私有 `.env` 中；使用后请保持固定并随私有配置备份，不要提交到 Git。只保存了哈希的历史 Key 会在下一次正常鉴权成功后补存加密副本，无法凭哈希直接还原。

使用 Python 3.12 和 uv。复制 `.env.example` 为 `.env`，默认通过器灵扫码登录，需要设置器灵服务地址 `QILING_API_BASE_URL`。本地使用密码登录时，设置 `AUTH_PROVIDER=password` 并填写管理员账号和密码。

已有依赖和 `.env` 时，在项目根目录执行 `./scripts/dev.sh` 同时启动完整前后端。浏览器打开 <http://127.0.0.1:3001/>；后端位于 <http://127.0.0.1:9000>，使用 `.env` 指定的 PostgreSQL 数据库。默认本地配置由启动脚本使用已安装的 PostgreSQL 工具，在 `127.0.0.1:15432` 管理项目专用实例，数据保存在 `data/postgres-local/`，不会使用 SQLite 或插入演示模型。密码登录模式下，管理员账号使用 `.env` 中的 `SUPER_ADMIN_USERNAME` 和首次创建时设置的密码。此启动方式不插入演示数据，也不安装依赖。

前台运行时按 Ctrl+C 停止；也可从另一个终端执行 `./scripts/dev.sh stop`。修改后端代码后重新启动此命令。PostgreSQL 数据库独立保留运行；需要停止时执行 `uv run --no-sync python scripts/local_postgres.py stop`。`CONSOLE_LOCALE=zh` 控制界面默认语言，与模型生成语言独立。模型调用需要在模型配置中填写有效供应商凭据；微信支付、器灵登录、对象存储各自按部署配置启用，单独启动应用不代表外部服务已经配置完成。

```sh
uv sync --frozen
uv run uvicorn main:app --host 127.0.0.1 --port 9000
```

- `/health` 检查服务及数据库。
- `/console-docs` 提供用户、模型配置和个人余额管理接口。登录后将返回的会话令牌作为 Bearer 凭据。余额、充值、API Key 与消费记录均归具体用户，管理员可管理用户状态、增额与退款。
- `/v1/docs` 和 `/v1/agent-guide.md` 提供模型调用说明。模型请求使用平台签发的 API Key。
- 平台支持文本、图片、异步视频和结算回执。临时素材上传需要配置独立的对象存储。
- Seedream 5.5 的方舟模型 ID 为 `doubao-seedream-5-5-261028`。新增 5.5 和 5.0 Pro 配置时可调整官方像素档位基准价；已有 Pro 配置可在模型配置中点击「填入官方像素分档价」并保存后切换。平台按上游返回的每张成功输出图的 `size` 分档，图层拆分传 `layer_decomposition: true`，输入参考图费用按请求计算一次，再按配置折扣结算。
- 平台数据库独立配置。部署时将 `/api/`、`/v1/` 转发到本服务。已有平台数据请先在数据库副本上验证升级。

管理员账号、供应商密钥、支付凭据和数据库连接通过部署环境配置。

## 控制台

控制台源码位于 `web/`，独立构建，无需其他项目。

```sh
cd web
npm ci
npm run dev
```

开发服务默认使用端口 3001，代理后端端口 9000。生产环境运行 `npm run build`，由 Web 服务器提供 `web/dist`，同时代理 `/api/`、`/v1/` 和 `/media/`。

升级旧版时，程序将原余额按所有者合并到个人账户，保留历史订单、流水和密钥；一次性迁移保留原始表，重复启动不会重复入账。升级前应完成数据库备份及副本演练。

历史作品迁移为可选兼容入口。仅迁移旧猫影站点时设置 `LEGACY_WORKS_ENABLED=true`，并将 `/api/legacy-works/` 转发到旧项目的独立只读归档服务。全新部署默认不显示此入口。归档服务保留原作品权限，不提供生成、修改或删除操作；作品包可导入本地猫影。

## 模型协议转发

原生接入使用供应商官方路径和 JSON 参数，保留任务 ID、结果、错误正文、状态码及安全的响应头；通道模型使用目录中的 `nv-ID` 或 `X-Cat-Model` 指定。完整路径见 `/v1/agent-guide.md` 和目录的 `native_api`。根路径与 `/v1` 下的同名原生路径均可使用。

临时上传规则保持：`/v1/media/uploads` 申请直传，文件直传 OSS 后使用 HTTPS URL 调用；不开放 Base64、data URL、内联媒体、multipart 或携带内联图片的流式输出。OpenAI／OpenRouter 图片上游必须支持 URL 结果；返回内联媒体的通道会明确拒绝，不自动上传或转码。

生成成功不依赖即时计费成功；异常在 `/v1/requests/{X-Cat-Request-Id}` 查询，已取得用量的结算会重试，缺少可确认用量的进入 review。文本流式调用建议显式 `stream_options.include_usage=true`，平台不替客户端改写此选项。

## Apifox 文档集成

公开定义地址为 `/v1/openapi.json`（OpenAPI 3.1），下载入口 `/api/platform/openapi-export`；仓库导入文件为 `docs/cat-api-openapi.json`。仅导出公开模型 API，不含管理接口、运行中的模型配置或真实凭证。

接口按视频／供应商、图片／渠道、LLM 和公共能力分组，使用 Apifox 官方 `x-apifox-folder` 多级目录字段。更新已有项目时，在 Apifox 导入选项中使用导入数据的目录，避免保留旧目录导致仍然平铺。

管理员可在“接口文档 → 文档设置”填写公开在线文档链接，保存后刷新页面应用 CSP 来源；也可用 `API_DOCUMENTATION_URL` 提供初始地址。数据库中的空字符串可暂停展示，并覆盖环境变量默认值。外部页面不会收到平台 Key；始终提供“新窗口打开”，以应对第三方拒绝嵌入。在线文档的主题和内部目录由 Apifox 发布配置控制。

OpenAPI 默认 server 为 `/v1`。通过文件导入 Apifox 时请设置对应测试环境地址；可使用 `PUBLIC_API_BASE_URL` 指定导出所用的公开 API 地址（包含 `/v1`）。本地路由和文件更新不会自动更改线上路由或已发布的 Apifox 内容，需要重新导入并发布。

若门户 HTML 由独立的 Caddy／Nginx 提供且该层设置了 CSP，还需在该层的 `frame-src` 仅加入已配置文档来源（当前为 `https://rjvutktiur.apifox.cn`）。后端的 HTML 响应中间件已按配置加入这一来源；不修改 `frame-ancestors` 或关闭站点防嵌套保护。
