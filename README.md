# Cat API

独立的模型 API 平台。工作台通过 HTTPS 和 API Key 调用平台。

## 本地运行

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
