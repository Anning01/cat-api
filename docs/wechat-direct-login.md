# 服务号微信直登配置

本实现直接对接微信服务号网页授权，不经过器灵。默认关闭，尚未使用真实公众号验证。公众号注册和认证完成后，再进行真实扫码联调。

## 账号归属

- 手机号对应的 Cat 用户 ID 是账户归属依据，余额、账单和 API Key 仍属于这个 ID。
- 微信身份仅按当前公众号 AppID + OpenID 匹配。数据库保存二者组合的 SHA-256 摘要，不按昵称、头像、UnionID 或器灵数字 ID 合并。
- 未绑定的微信扫码确认后，需要在原登录页面验证手机号。已绑定手机号登录原账号并关联微信；开启 `PHONE_SIGNUP_ENABLED` 时，同意协议的新手机号自动创建账号并关联微信。已绑定的微信可直接扫码登录。
- 微信已经属于另一账号，或手机号账号已绑定另一个微信时，拒绝覆盖或合并。换绑/找回不在本次范围。
- 成功关联后，后续微信扫码可直接登录；每次检查用户状态和手机号绑定仍然有效。
- 未绑定手机号的老器灵用户，应先通过原入口进入个人中心绑定手机号；不能凭昵称迁移。

## 配置

首先完成 [手机登录配置](phone-login-migration.md)。微信首次绑定依赖真实短信验证，短信未配置时微信入口也保持关闭。

```dotenv
WECHAT_LOGIN_ENABLED=true
WECHAT_LOGIN_APP_ID=填写服务号AppID
WECHAT_LOGIN_APP_SECRET=仅在服务器安全配置
WECHAT_LOGIN_ORIGIN=https://shortdramas.xiazq.com
```

`WECHAT_LOGIN_ORIGIN` 是固定外网 HTTPS 来源地址，不包含路径、查询参数或尾部斜线，不从客户端 Host 或请求参数推断回调地址。

固定回调地址：`https://shortdramas.xiazq.com/api/auth/wechat/callback`。

公众号后台设置「网页授权域名」为 `shortdramas.xiazq.com`，按后台要求校验域名。把下载的 `MP_verify_*.txt` 校验文件原样放到 `web/public/` 后构建发布，使其能从站点根路径访问；后续发布保留该文件。不要误填器灵域名，也不要把 AppSecret 放入前端环境变量或源码。

迁移期可以保留 `AUTH_PROVIDER=qiling`，以保留「老用户登录」入口。微信配置可用时登录页默认展示自建微信入口，同时提供手机登录。完成老用户迁移后设置 `AUTH_PROVIDER=wechat`，器灵接口及入口关闭；微信不可用时可选择短信登录。

公众号必须具备网页授权权限。本方案使用 `snsapi_base` 只获取登录所需的 OpenID，不请求昵称、头像。自有登录状态由 Cat API 签发。

## 流程与接口

1. `POST /api/auth/wechat/start`：创建 5 分钟二维码。私有 attempt 仅返回发起登录的浏览器；二维码仅包含独立的 OAuth state。
2. `GET /api/auth/wechat/callback`：单次认领 state，以 code 向固定微信接口换取身份，手机上显示确认页面。浏览器令牌与微信 access_token 都不会放入地址栏或这个页面。
3. `POST /api/auth/wechat/confirm`：手机提交独立的一次性确认秘密。确认后留 5 分钟完成登录或手机号验证。
4. `POST /api/auth/wechat/poll`：只有持有私有 attempt 的原浏览器能查询。已绑定者获取一次登录会话；未绑定者返回 `phone_required`。
5. `POST /api/auth/phone/login`：携带短信 challenge、验证码和 `wechat_attempt`；短信消费、手机号账户创建（如适用）、微信关联及登录会话在同一事务内完成。绑定冲突会回滚，不留下半创建的账号。

每次 start、poll、短信入口均限流。回调 state、确认秘密和浏览器 attempt 独立生成，数据库只保存摘要；回调重复调用不能再次兑换身份。网络失败、超时、过期、配置切换均拒绝继续。并发领取最多签发一个会话。浏览器退出步骤时取消请求和轮询，避免旧结果覆盖新流程。

在手机微信内点击授权时使用当前标签页跳转，私有 attempt 仅短期保存于原站点的 `sessionStorage`。确认页提供固定的本站登录页链接，返回后继续原 attempt，不把秘密放入 URL。切换登录方式、登录成功或过期会清除保存值；二维码仍可用于电脑扫码场景。

## 上线验收

- 确认新增 `wechat_identities`、`wechat_login_attempts` 已建表，和短信配置、服务协议、隐私说明一并准备好。自动建表关闭时先在数据库副本验证建表流程。
- AppID/AppSecret、域名校验和网页授权权限都完成后，再开启功能；仅设置开关不能绕过缺少凭据的检查。
- 两个不同微信、两个不同手机号完成首次绑定及二次扫码测试，验证各自账号、余额及 Key 归属。
- 验证微信 A + 手机 B 的冲突场景、过期二维码、拒绝确认、重复回调和停用账号。
- 检查手机微信内授权，以及电脑扫码后原页面继续验证的流程；真实微信行为与权限问题无法用模拟接口完全替代。
- 代理/日志不要记录请求体或 Authorization；应用不记录微信交换接口的 URL、响应和凭据。入口的回调 query 含短期 code/state，访问日志应按部署要求脱敏并限制访问，不能作为账号迁移依据。

关闭 `WECHAT_LOGIN_ENABLED` 可停用微信直登但保留短信登录及已建立的绑定。更换公众号 AppID 不会继承旧微信身份，不能直接把旧绑定改成新 AppID。

参考：[腾讯公众号网页授权接入说明](https://docs.cloudbase.net/integration/wechat-official-oauth)。
