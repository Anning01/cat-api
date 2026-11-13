# 软件端升级对接说明：Cat API 协议转发与 Seedream 5.5

日期：2026-11-14。交付对象：猫影（novel-vids）及其他 Cat API 接入软件的开发者。

**当前是本地待发布契约，Cat API 尚未部署。先在本地／测试环境联调，确认后再安排双方上线。本文不要求立即切换线上地址或重写所有旧调用。**

## 1. 哪些需要改，哪些可以继续使用

| 项目 | 软件端动作 | 兼容说明 |
| --- | --- | --- |
| 临时素材上传 | 保持现有流程 | `/v1/media/uploads` 申请票据，文件直传 OSS，随后传 `read_url`。不接收 multipart、Base64 文件、data URL 或内联媒体 |
| 原有文本和图片调用 | 保留接口，核对返回和回执解析 | `/v1/chat/completions`、`/v1/images/generations` 继续提供；成功正文和扩展字段不再人为重组 |
| 平台账务回执 ID | 优先读取 `X-Cat-Request-Id` | 仍保留 `X-Novelvids-Request-Id`。不能只拿供应商的 `X-Request-Id` 当平台 UUID |
| 文本流式用量 | 确认请求明确带 `stream_options.include_usage=true` | 平台不再替客户端强制添加。缺少可确认用量时，生成内容仍返回，账单进入核对 |
| 原有视频调用 | 可继续走 `/v1/videos` | 原 `duration/resolution/aspect_ratio/references`、统一任务 ID 和 `metadata.url` 兼容结构保留，不强制迁移 |
| 新增供应商原生视频 | 按需增加适配器 | 使用第 6 节的原生路径，按供应商自己的任务 ID、状态及结果字段解析，不能套旧 `/videos` 解析器 |
| Seedream 5.5 | 软件发布版本必须包含模型类型、报价和结算支持 | 只改展示名称不够，详见第 4 节 |
| 语音识别、画质增强 | 需要使用时接入原生提交／查询 | 已补齐公开入口；不能因为目录里有模型，就沿用图片／视频的解析和计费逻辑 |

普通用户不需要重新创建所有 Key。需检查原 Key 是否到期、是否授权了新模型；指定模型的 Key 要显式授权新增 5.5 的目录 ID。

## 2. 猫影本机源码的核查结果

以下是本次读取工作台源码得到的事实，不代表打包版本已发布，也不代表已与真实供应商联调：

- `utils/enums.py`、`services/image_generation/capabilities.py`、`web/src/types.ts` 已加入 `seedream_5_5`。
- `services/billing/pricing.py` 已有 `image_price_tier()`、`pixel_receipt_cost()`，工作台的前端报价与后端预估已出现像素档位支持。
- `services/billing/platform.py` 已有按 `usage.output_tier_counts` 结算像素价的分支，缺失用量时进入 review。
- 回执捕获当前优先读取 `X-Novelvids-Request-Id`，因此可继续兼容；建议增加新头 `X-Cat-Request-Id` 为第一优先级。
- `services/image_generation/gateway.py` 已兼容 `data` 与 `images` 两种图片列表，按 URL 下载的逻辑可以保留。
- `services/studio_platform.py` 仍对整份目录使用严格枚举校验。请防止未来未知模型类型导致所有模型同步失败。
- 普通目录同步仅在新建配置时写入价格；已有配置的本地售价不会自动覆盖。这是需要保留的价格边界，升级 Pro 价格要走明确的导入／编辑操作。
- 工作台已有读取平台图片价的入口：`GET /api/config/studio-platform/image-tariff/{config_id}`。请复用，不再新造另一套同步接口。

因此：不要重复实现已经存在的 5.5 与像素计费代码；先确认上述代码进入实际发布版本，再补齐回执头读取、容错、发布和联调。

## 3. 必须核对的共同调用规则

### 3.1 模型、通道和回执要分别保存

从 `GET /v1/models` 的 `data[]` 获取模型，以 `id`（如 `nv-42`）区分配置。示例 ID 不是实际可用模型，请使用当前目录返回的值。

同名模型可有多条渠道、价格和折扣，不按名称去重，也不根据回复中的 `model` 反查本地配置。保存发起调用时选择的目录 ID、本地配置 ID、幂等键和价格快照。上游回复中的 `model` 现在保留供应商原值，可能不等于 `nv-42`。

平台回执编号与供应商任务编号是两个不同标识：

```python
platform_request_id = (
    response.headers.get("X-Cat-Request-Id")
    or response.headers.get("X-Novelvids-Request-Id")
)
provider_request_id = response.headers.get("X-Request-Id")
```

兼容旧平台时，可在前两个头都没有、且已确认连接的是旧 Cat API 时，尝试将 `X-Request-Id` 作为 UUID 解析；新代码不要把任意供应商追踪 ID 当平台回执编号。

回执查询接口保持不变：

```text
GET {BASE_URL}/requests/{platform_request_id}
GET {BASE_URL}/requests?request_key={original_idempotency_key}
```

`BASE_URL` 的本地示例为 `http://127.0.0.1:3001/v1`。部署在其他进程、容器或机器的软件，应使用它实际能访问的测试地址，不能照抄 localhost。

### 3.2 生成成功与结算成功分别处理

| settlement.status | 软件端处理 |
| --- | --- |
| `settled` | 使用 `settlement.amount`，按字符串转 Decimal，保留六位小数；平台金额已包含平台折扣，不再重复打折 |
| `pending` | 保留图片／视频／文本结果，继续查询账单，不重新发起生成 |
| `review` | 保留结果和回执，显示待核对；不记成零元或自动生成第二次 |
| `not_charged` | 平台已确认不收费，不扣平台费用；本地账按既有规则核对 |

收到 200 也要检查供应商正文里的 `error` 等业务错误；不能假定全部错误都会变成 HTTP 4xx／5xx。遇到断线、超时或提交结果不确定，先用原幂等键查询平台回执，不盲目换键重发。

工作台的团队本地售价与平台成本继续分开：`platform_cost` 取平台已结算金额；本地计费按调用受理时的本地价格快照计算，不能在任务完成后读取新价追溯重算。

### 3.3 文本流式输出

显式请求用量：

```python
stream = client.chat.completions.create(
    model=selected_catalog_id,
    messages=messages,
    stream=True,
    stream_options={"include_usage": True},
)
```

使用原有支持 SSE 的 SDK，容忍心跳、空 choices 和扩展字段；保留工具调用、推理字段和 finish_reason。前端是否展示推理内容由软件决定，不能在网络层丢弃后影响后续工具调用。使用的框架可能已经代发 include_usage，需要检查真实发出的请求，不必另写流解析器。

## 4. Seedream 5.5 与 5.0 Pro 像素分档

### 4.1 模型同步和展示

- `image_model_type` 为 `seedream_5_5`，展示名称 Doubao Seedream 5.5。
- 工作台同步配置继续使用 `api_protocol="novelvids"`；不要把平台 Key 改成供应商协议或误传给供应商。
- Cat API 当前将 5.5 的选项复用为 Pro 的 1K／1.5K／2K、现有画幅和 PNG／JPEG。软件应与当前能力配置保持一致，实际供应商支持仍需联调，不自行扩展选项。
- 读取并保留 `pricing.type`、`currency`、`billing_unit`、全部 `prices`、`input_image` 和 `discount`。不能把 `prices["2K"]` 缺失解释为免费。
- 未知未来模型类型应单项标记不支持或跳过，并说明原因，不能让其他已支持模型整份同步失败，也不能据此清空全部已有配置。

目录报价结构示例（金额仅为仓库默认值，实际使用当前通道发布的报价）：

```json
{
  "id": "nv-42",
  "name": "Seedream 5.5",
  "kinds": ["image"],
  "task_types": [2],
  "image_model_type": "seedream_5_5",
  "pricing": {
    "type": "image",
    "currency": "CNY",
    "billing_unit": "pixel_tier",
    "prices": {"low": 0.13, "high_capped": 0.23},
    "input_image": {"first_free": 0, "price_per_image": 0.05},
    "discount": 1
  }
}
```

### 4.2 档位与结算依据

P 为单张成功输出图片的实际宽 × 高；1 MP 为 1,000,000 像素。以下均为当前仓库默认人民币基准价，不是额外承诺的固定售价。

| 模型／模式 | P ≤ 2,610,000 | P > 2,610,000 | 输入参考图费用 |
| --- | --- | --- | --- |
| 5.5，单图或拆层 | `low`：0.13 元／张 | `high_capped`：0.23 元／张，最高 4,630,000 像素 | 每张 0.05 元，首张也收费 |
| 5.0 Pro，单图 | `single_low`：0.30 元／张 | `single_high`：0.60 元／张 | 每次请求首张免费，之后每张 0.02 元 |
| 5.0 Pro，拆层 | `layer_low`：0.15 元／张 | `layer_high`：0.30 元／张 | 同上，每次请求计算一次，不对每张输出重复收输入费 |

平台回执示例（按上述 5.5 基准价、两张输入参考图、一张低档输出）：

```json
{
  "id": "11111111-1111-4111-8111-111111111111",
  "model": "nv-42",
  "status": "completed",
  "usage": {
    "image_count": 1,
    "clarity": "1.5K",
    "input_image_count": 2,
    "output_tier_counts": {"low": 1},
    "layer_decomposition": false
  },
  "settlement": {"status": "settled", "amount": "0.230000", "currency": "CNY"},
  "pricing": {
    "type": "image", "currency": "CNY", "billing_unit": "pixel_tier",
    "prices": {"low": 0.13, "high_capped": 0.23},
    "input_image": {"first_free": 0, "price_per_image": 0.05}, "discount": 1
  }
}
```

本地像素价使用 `usage.output_tier_counts` 的每档数量乘本地快照对应单价；参考图使用 `input_image_count`，再应用该份本地快照的折扣。平台金额不再套本地售价或二次折扣。

`clarity` 是请求／兼容信息，不能替代实际输出分档。缺少实际尺寸、缺少档位数量、档位无报价或数量不一致时，账单进入核对；生成 URL 仍可交付。5.0 Pro 的旧清晰度价与新像素价可以同时存在，按每个配置的 `billing_unit` 分支，不按型号一刀切。

### 4.3 生成和参考素材

普通 5.5 资产生成继续使用 `POST /v1/images/generations`，传选定的目录 ID、提示词、能力允许的像素尺寸、参考图 HTTPS URL。工作台原有 `image` URL 数组继续兼容，不必为 5.5 改成新的视频接口。

```json
{
  "model": "nv-42",
  "prompt": "保持参考图中的人物特征，生成新的场景",
  "size": "2048x1152",
  "image": ["https://temporary-storage.example/reference.png"],
  "n": 1,
  "output_format": "png",
  "response_format": "url"
}
```

普通生成不传 `layer_decomposition` 或传 false。产品确实开放拆层时才传 `layer_decomposition: true`，保留每个成功底图／图层及上游相关字段，不只取第一张。该功能需要单独做供应商联调；软件不能因为收到多张结果而自动再次生成。

使用 OpenAI 官方 URL 编辑形状时，发送 `POST /v1/images/edits` 与 `images: [{"image_url":"https://..."}]`；可选 mask 也是 `{"image_url":"https://..."}`。OpenRouter 原生图片入口为 `POST /v1/images`，参考图用 `input_references`。平台继续禁止 multipart、文件 ID 和内联媒体；上游通道必须支持 URL 输出。

## 5. 本机检查与建议发布顺序

本次检查时，本机 Cat API 的公开启用目录中尚未出现 `seedream_5_5` 配置。代码支持型号，不等于已经添加了有效上游模型和价格。以下操作由双方在测试环境确认后执行：

1. 软件端确认当前源码里的 5.5、报价、分档结算支持已进入待发布版本，补齐共同规则与验收。
2. Cat API 在本地配置有效的 5.5 通道，保存实际上游模型 ID、合法凭证、像素价和折扣；对联调 Key 授权对应 nv-ID。不要在文档或代码里填写真实密钥。
3. 软件端同步目录。已有 Pro 配置若要改用像素价，先由管理员明确导入平台价或编辑本地售价；常规同步不覆盖自定义本地价。
4. 在本地完成旧流程回归、新模型和账单联调。确认生成结果、平台账和工作台本地账各自对应同一次请求。
5. 双方确认后安排发布。先确保软件兼容，再向旧版本 Key 放开新型号；旧任务继续使用原价格快照和原查询入口。

本次不部署，也不要求软件开发者直接切换线上通道。

## 6. 可选：供应商原生任务适配

新适配器读取目录的 `native_api`。下面路径可直接接平台域名，也可接含 `/v1` 的 Cat API Base URL；统一一种拼接方式，避免误删或重复添加路径片段。

| 协议 | 提交 POST | 查询 |
| --- | --- | --- |
| Seedance | `/api/v3/contents/generations/tasks` | GET `/api/v3/contents/generations/tasks/{task_id}` |
| MiniMax H3 | `/v2/video_generation` | GET `/v2/query/video_generation/{task_id}` |
| Wan | `/api/v1/services/aigc/video-generation/video-synthesis` | GET `/api/v1/tasks/{task_id}` |
| AutoDL | `/api/v1/comfyui/comfyui_workflow/{model_id}` | GET `/api/v1/comfyui/comfyui_workflow/result/{task_id}` |
| MediaKit 增强 | `/api/v1/tools/enhance-video-generative` | GET `/api/v1/tasks/{task_id}` |
| SeedASR | `/api/v3/auc/bigmodel/submit` | POST `/api/v3/auc/bigmodel/query`，JSON `{}` |

- 有 model 字段时使用目录 ID；没有该字段或同名多通道时用 `X-Cat-Model: nv-ID`。AutoDL 的路径 model_id 也可使用目录 ID。
- 原生查询按供应商自己的状态与结构解析，例如 Seedance `succeeded/content.video_url`、Wan `output.task_status/output.video_url`，不套旧统一视频的 `completed/metadata.url`。
- 平台回执 ID 仍从 `X-Cat-Request-Id` 获取，供应商任务 ID 单独保存；不要互换。跨账户任务不允许查询。
- SeedASR 使用 `audio.url`；`X-Api-Key` 填平台 Key，`X-Api-Resource-Id` 选对应资源，`X-Api-Request-Id` 提交与查询保持一致。保留 `X-Api-Status-Code`、`X-Api-Message` 和 `X-Tt-Logid`。
- MediaKit 使用 video_url；识别和增强按供应商实际结果确认用量，不通过猜测时长扣款。
- 原生查询与旧 `/v1/videos` 分开保存路由，不能把历史统一任务 ID 直接送进新的原生查询接口。

## 7. 交付验收清单

| 用例 | 预期 |
| --- | --- |
| 目录混合 5.5、新价 Pro、旧价 Pro、其他已支持模型和未知未来类型 | 已支持项可同步；未知项有明确提示，不拖垮整份目录 |
| 原有文本、URL 图片和 `/v1/videos` 调用 | 旧流程继续可用，不要求全部改原生视频 |
| 三个请求头同时存在，供应商 X-Request-Id 不是 UUID | 平台回执取 X-Cat-Request-Id；旧客户端仍可取 X-Novelvids-Request-Id |
| 文本流式带 include_usage=true | 正文、工具调用和最终 usage 可读取；缺 usage 不丢正文、不盲目重发 |
| 5.5 边界模拟：两张参考图，一张 2610×1000 输出 | 基准价 0.13 + 2×0.05 = 0.23 元；2611×1000 时 0.33 元 |
| 上述 5.5 价格配置五折 | 平台金额分别为 0.115000、0.165000；客户端不再重复打折 |
| Pro 拆层，两张参考图，一张低档、一张高档 | `output_tier_counts` 含 layer_low=1、layer_high=1；基准价 0.47 元，五折 0.235 元 |
| 有成功 URL，但供应商未报告可确认的尺寸 | 保留图片；账单 review，不能零元结算或重新生成 |
| 收到超出请求授权数量的图片 | 原样保留结果，账单核对，不擅自多扣或截断响应 |
| 同一请求重复查询、软件重启后恢复查询 | 同一回执只扣一次费；任务与原价格快照继续关联 |
| 原生视频响应包含未知字段 | 字段不丢失，按该供应商状态解析；供应商 ID 与平台 UUID 分开 |
| 普通用户的 Key 尝试查询其他账户任务 | 拒绝，不返回他人任务或账单 |

Cat API 本地证据：96 项后端测试（含独立临时 schema 的 PostgreSQL 验证）、51 项前端测试和构建通过。覆盖本地模拟供应商协议，不等于双方软件已完成真实供应商联调。请软件端交付对应版本、改动清单与上述验收结果后，再一起确认发布。
