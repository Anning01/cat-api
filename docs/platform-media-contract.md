# 画质增强与语音识别平台契约

状态：目录和素材准备已实现；以下任务路由为提案，尚未注册、不能调用。
本文件不宣称供应商转发或真实结算已通过。工作台当前仍需从 MediaKit/SeedASR 原生执行器适配到本协议。

## 已实现目录

`GET /v1/models` 使用现有 Bearer 用户 Key；studio 与普通 API Key 沿用既有读取策略。仅返回 active、official 且非 novelvids 转发配置。停用、删除、team 配置均不返回。目录每次读取当前配置，无缓存快照。

- `id`: `nv-<配置编号>`，名称不加编号后缀。
- `task_types=[8]`, `kinds=["media_processing"]`；`pricing.type=media_processing`，`billing_unit=minute`，`tiers` 为管理员实际配置的 `short_side_max/fps_max/price`。
- `task_types=[9]`, `kinds=["asr"]`；`pricing.type=asr`，`price_per_minute` 为管理员实际配置。
- 每项 `concurrency` 为当前模型配置的正整数并发上限。现有 admission 按该模型所有账户的活跃请求合计限流；此值是单工作台可采用的客户端上限，不是预留额度，不保证多个账户同时各获该额度；共享繁忙仍返回 429。供应商 `account_concurrency` 不公开。如需每账户预留额度，需另行配置与限流实现，不能复用供应商总并发。
- 增强 `processing_options` 仅公开：`input_short_side_min/input_short_side_max/input_long_side_max/input_fps_min/input_fps_max/max_duration_seconds/max_file_bytes/poll_seconds/local_upload_max_bytes/output_resolutions`。缺省来自现有 EnhancementOptions。队列、供应商地址和凭据不返回。

工作台成功同步后，应删除此前同步但本次已缺失/停用的配置；同步失败不得清理。首次同步和后续更新均按 `id` 合并，更新价格、能力、并发。

## 已实现素材准备

沿用 `POST /v1/media/uploads`，入参仍为 `content_type/byte_length/content_md5`；响应新增 `media_id`，原 `upload_url/headers/read_url/expires_at` 保持兼容。客户端先按 headers PUT 内容，成功后才能提交任务。音频/视频不通过 JSON Base64 上传。

服务端 `owned_media_url(user_id, media_id, kind)` 只解析当前账户、未过期、匹配存储桶和媒体扩展名的 lease，重新签发 GET；禁止从另一个账户取得输入地址。该校验只证明租约归属和类型声明，不证明文件已上传、真实格式或可解码。接通执行器前还必须 HEAD/探测真实内容、验证大小、音视频流、时长和尺寸；不能信任客户端用量或扩展名，也不能把音轨所在 mp4 的视频租约直接当作音频。

## 待实现任务路由

统一采用异步 job，避免长音频同步超时后重复付费：

| 方法 | 路径 | 含义 |
|---|---|---|
| POST | `/v1/audio/transcriptions` | 提交识别，返回 202 job |
| GET | `/v1/audio/transcriptions/{id}` | 查询识别结果 |
| POST | `/v1/video-enhancements` | 提交画质增强，返回 202 job |
| GET | `/v1/video-enhancements/{id}` | 查询增强结果 |
| GET | `/v1/video-enhancements/{id}/content` | 完成后 307 跳转到短期签名结果地址 |

POST 请求必须带 `request_id`（UUID）；可同时带 `Idempotency-Key`，二者必须一致。请求 schema 在 `schemas/platform_media.py`，未知字段拒绝，供应商凭据/地址/队列不能作为客户端字段。

识别示例：

```json
{"model":"nv-42","media_id":123,"request_id":"12345678-1234-1234-1234-123456789abc"}
```

增强示例：

```json
{"model":"nv-43","media_id":124,"request_id":"12345678-1234-1234-1234-123456789abd","output_resolution":"1080p"}
```

`output_resolution` 取 720p/1080p/2k/4k 且必须在所选模型公开能力中。服务端探测后复用 `validate_source/require_upscale` 校验 SDR、尺寸、帧率、时长及大小；输出规格必须有完整费率。不接受客户端填写时长来决定账单。

最终识别响应形状示例（仅说明格式，非真实调用记录）：

```json
{"id":"12345678-1234-1234-1234-123456789abe","object":"transcription","model":"nv-42","status":"completed","billing_status":"completed","duration_seconds":"2.5","text":"你好","segments":[{"start":"0.2","end":"1.8","text":"你好"}],"download_url":null}
```

job `id` 是平台回执 UUID，区别于客户端 request_id；时间轴、duration_seconds 全部为秒，十进制字符串；供应商毫秒时间戳必须除以 1000。时间轴不允许负数、NaN、end < start。增强 object 为 `video_enhancement`，完成时提供 download_url，text/segments 为 null。结果链接过期后 GET 可刷新地址，不能重新提交付费任务。

## 受理、恢复及账务要求

复用现有 developer_identity、admit、PlatformCallReceipt、request_keys 和账户钱包。模型必须 active/official、包含正确任务类型并使用支持的上游协议，禁止 novelvids 循环转发。所有 job/回执/下载查询均以当前 Key 所属 user_id 限定，不返回供应商任务号或原始含秘密的错误体。

admit 在同一事务里执行幂等、价格快照、余额与并发检查；新增任务必须与受理记录可靠绑定并可重启恢复。相同账户相同 request_id+相同 payload 应返回原 job；不同 payload 返回 409 和原回执编号，不再次调用供应商。即使模型后来停用也必须能查询已受理任务。POST 响应丢失后，通过已有 `GET /v1/requests?request_key=<request_id>` 恢复平台编号，再查询 job；新任务 GET 还需支持原 key 恢复（例如 query `request_key`，与已有视频 req-UUID 风格保持一致）。

| 任务状态 | 回执状态 | 客户端操作 |
|---|---|---|
| queued/in_progress | submitted/processing | 查询原 job，刷新页面后继续 |
| completed | measured/settling | 结果可用，等待结算回执 |
| completed | completed | 结果可用，账单 settled |
| failed | rejected | 已确认未成功，not_charged；用户决定新 request_id 重试 |
| review | review | 受理或用量不确定，人工核对；禁止自动新建付费任务 |

未知超时、连接中断、上游 5xx 不等于拒绝，保留原请求和供应商编号，进入 review 或继续按原编号查询。不得将 review 显示为可以自动重试的 failed。不自动重发提交；只有明确未受理或终态失败才能允许新请求。刷新恢复与多进程轮询须有数据库认领，不能重复计费。

现有 `GET /v1/requests/{id}` 回执格式保持不变：usage 保存真实供应商/服务端验证的用量；pricing 是受理快照；settlement.status 为 pending/review/not_charged/settled，只有 settled 有实际 amount。

ASR 计划复用 compute_asr_cost：真实音频秒数 / 60 × 配置 price_per_minute × discount。增强计划复用 enhancement_cost：真实输出秒数 / 60 × 输出短边与帧率对应档位 × discount。按六位小数 HALF_UP。必须拒绝缺失/非有限/不正用量，不把缺测当免费或猜测计费。settle 增加两个显式类型分支及 task_type 映射，继续使用 measured→settling→completed 原子事务和 consume；未知类型不能落入文本计费。真实用量缺失保留 review。

例如 ASR 60 秒、0.015 元/分钟、discount=1，预期结算 amount="0.015000"；这是算法验算，不是实际扣款证明。

## 接通前的人工审核与验收

尚未新增供应商 HTTP 执行器、任务表/恢复器、任务路由或 settle 分支，未改变任何现有扣费路径。项目没有找到额外本地 AGENTS.md；本次按任务明确要求，对新增外部计费链路保留人工审核。审核本契约后，下一阶段应完成：

1. 按官方供应商协议实现 MediaKit 和 SeedASR 服务端适配器、错误脱敏和可靠任务持久化；核实提交幂等/供应商回查能力，不能凭空假定支持。
2. 增加真实媒体探测、下载域名与重定向访问限制、租约到期处理；供应商密钥仅在服务端使用。
3. 补充双账户隔离、并发提交、断线不确定、重启续接、轮询竞争、重复结算、余额不足及结果链接续签测试。
4. 审核计价用量来源、费率快照、折扣和原子结算；随后再接工作台适配。
5. 用户单独授权后再做小额真实识别与增强调用，并分别记录供应商任务、用量、平台回执和真实扣款；不可用测试替身或目录出现充当端到端通过。

本次不部署、不推送、不改变生产余额，不调用真实付费模型。
