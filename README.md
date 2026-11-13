# Cat API

独立的模型 API 平台。工作台通过 HTTPS 和 API Key 调用平台。

## 本地运行

使用 Python 3.12 和 uv。复制 `.env.example` 为 `.env`，设置自己的管理员账号和密码。

```sh
uv sync --frozen
uv run uvicorn main:app --host 127.0.0.1 --port 8000
```

- `/health` 检查服务及数据库。
- `/console-docs` 提供账号、团队、模型配置和余额管理接口。登录后将返回的会话令牌作为 Bearer 凭据，团队操作通过 `X-Team-Id` 指定团队。
- `/v1/docs` 和 `/v1/agent-guide.md` 提供模型调用说明。模型请求使用平台签发的 API Key。
- 平台支持文本、图片、异步视频和结算回执。临时素材上传需要配置独立的对象存储。
- 平台数据库独立配置。部署时将 `/api/`、`/v1/` 转发到本服务。已有平台数据请先在数据库副本上验证升级。

管理员账号、供应商密钥、支付凭据和数据库连接通过部署环境配置。
