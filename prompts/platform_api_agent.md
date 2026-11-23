# 猫影模型 API：AI Agent 接入说明

Base URL：`{{BASE_URL}}`

公共对话和 URL 图片接口保留上游返回。视频生成使用目录公布的 /videos 或原生入口。识别和增强使用各自原生协议。

## 认证与模型

在猫影开放平台创建 API Key，保存到 `NOVELVIDS_API_KEY` 环境变量。发送 `Authorization: Bearer <API_KEY>`，使用该 Key 所属用户的团队权限与余额。

`GET /models` 对普通客户端默认返回平台已有的公开调用别名，例如 `gpt-image-2.6-sunburst-discount`，`name` 与该 ID 相同，不下发后台随意填写的显示昵称。客户端把该名称填入 `model`，平台按现有别名找到唯一配置，再使用供应商原模型名转发；例如公开调用名 `gpt-image-2.6-sunburst-discount` 对应供应商 `gpt-image-2.6-sunburst`。后缀区分渠道，保留各自价格与权限，不合并多渠道、不改路由策略。

用途按 OpenRouter 目录形式返回 `architecture.input_modalities/output_modalities/modality`，同时提供顶层 input_modalities/output_modalities；例如 text->text 是文本输出、text+image->image 是生图、audio->text 是识别、text->audio 是音色设计。不能把支持图片输入误标为图片生成。`endpoints` 列出平台实际提供的路径；供应商原生协议依旧按对应路径调用，目录有模型不代表任意第三方软件已适配该协议。不编造未知上下文长度或未核实的识图能力。

`legacy_id` 保留内部授权编号；普通目录仍按当前 Key 的 nv-ID 授权过滤。显式请求 `/models?identifier=legacy` 可取得历史 nv-ID 目录；工作台现有 `X-NovelVids-Capabilities` 请求头也保留该兼容视图。API Key 的用途名称不影响普通客户端的命名格式；`identifier=alias` 可显式请求公开别名视图。已有 nv-ID 和旧别名调用继续可用。

参考：[OpenAI 模型对象](https://developers.openai.com/api/reference/python/resources/models/methods/list)、[OpenRouter 模型目录](https://openrouter.ai/docs/guides/overview/models)。用途元数据采用公开扩展格式，既有 pricing 继续使用 CNY 与平台实际配置，不冒充 OpenRouter 的 USD 价格。

```python
import os
from openai import OpenAI

BASE_URL = "{{BASE_URL}}"
API_KEY = os.environ["NOVELVIDS_API_KEY"]
client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
for model in client.models.list().data:
    print(model.id, model.name, model.kinds)
```

尺寸、时长、参考图数量与工具能力以所选模型配置为准。Seedance、MiniMax、Wan 原生 SDK 的路径和协议不同，接入本文公共接口时使用以下 JSON 协议。

## 临时素材：POST /media/uploads

用户已有的 HTTPS 地址和带 MIME 的 Base64 data URL 可随生成请求提交。只有供应商需要拉取本地媒体时才申请临时上传。票据按账户限额管理，客户端按返回地址直传至配置的存储。

```python
import base64
import hashlib
from pathlib import Path
import requests

def upload_reference(path: str, content_type: str) -> str:
    source = Path(path)
    with source.open("rb") as file:
        checksum = hashlib.file_digest(file, "md5").digest()
    # Base64 只用于固定长度 MD5 摘要，不编码文件内容。
    response = requests.post(
        BASE_URL + "/media/uploads",
        headers={"Authorization": "Bearer " + API_KEY},
        json={"content_type": content_type, "byte_length": source.stat().st_size,
              "content_md5": base64.b64encode(checksum).decode()},
        timeout=30,
    )
    response.raise_for_status()
    ticket = response.json()
    with source.open("rb") as file:
        uploaded = requests.put(ticket["upload_url"], headers=ticket["headers"], data=file, timeout=600)
        uploaded.raise_for_status()
    return ticket["media_ref"]

reference_url = upload_reference("reference.png", "image/png")
```

upload_url 的 PUT 授权有效期为 10 分钟。上传时只发送票据内的 headers。将 media_ref 原样填入生成请求的媒体字段，它只能由同一账户使用。临时文件最长保留 48 小时，过期后重新上传。普通 JSON 上限 1 MiB，带 Base64 的媒体请求总上限 16 MiB。`/images/edits` 和 `/videos` 还支持文件表单。

## 对话：POST /chat/completions

```python
stream = client.chat.completions.create(
    model=os.environ["NOVELVIDS_TEXT_MODEL"],
    messages=[{"role": "user", "content": "写一个简短开场"}],
    stream=True,
    stream_options={"include_usage": True},
)
for chunk in stream:
    if chunk.choices:
        print(chunk.choices[0].delta.content or "", end="")
```

返回上游原始 ChatCompletion 或 SSE 事件与 `[DONE]`，不包裹 data/result，不重写返回 model。建议显式请求 include_usage；平台不会修改该选项，缺少 usage 时仅将账单记为待核对，不影响成功结果。保留 tools、tool_choice、response_format、tool_calls、tool_call_id 与模型扩展字段。多模态图片使用 image_url.url 中的 HTTPS 链接。普通文本渠道不开放音频 Base64 输出；task_types=[12] 的音色设计渠道支持下述 WAV 返回契约。

## 音色设计：POST /chat/completions

从 `/models` 选择 `task_types=[12]`、`kinds=["voice_design"]` 的已启用渠道；使用返回的 `nv-ID` 或别名，不把供应商模型名当平台编号。后台超管通过现有 `/api/config` 配置独立 task_types=[12]、api_protocol=openai_compatible、text_api=chat_completions、model=mimo-v2.5-tts-voicedesign，供应商地址为 `https://api.xiaomimimo.com/v1`，密钥仅保存在平台。启用前须配置 pricing.type=voice_design、billing_unit=second、currency=CNY、price_per_second（非负数字）。不提供默认收费单价，不自动创建或启用渠道。

```json
{"model":"nv-<目录实际编号>","messages":[{"role":"user","content":"沉稳、有磁性的年轻男声"},{"role":"assistant","content":"你好，这是我的试听台词。"}],"audio":{"format":"wav","optimize_text_preview":false},"stream":false}
```

使用 Bearer 用户 Key 和 `Idempotency-Key`；响应保持供应商原始 JSON，`choices[0].message.audio.data` 为 Base64 WAV。保留样本全部字节，不裁剪、不固定为若干秒；客户端保存时应自行校验音频。此专用渠道仅支持非流式单音频输出，必须同时提供描述和试听台词，不支持音频克隆输入。

`X-Cat-Request-Id` 为本次平台回执 UUID；供应商自己的 `X-Request-Id` 保持原义。查询 `/requests/{id}` 或 `/requests?request_key=<原幂等键>` 获取 `usage.seconds` 和实际结算金额。重复幂等键返回 409 和原回执编号，不能因此自动换键重发。

计费取完整 WAV 的实际样本帧数 / 采样率，按秒数 × 受理时后台每秒单价 × discount 结算，金额按六位小数 HALF_UP；不按等待耗时、文本长度或供应商 token 数计费，不向上取整秒，也不套用语音识别每分钟费率。usage 同时保存 frames/sample_rate 用于精确复核。没有可靠 WAV 时保留响应供客户端校验，回执为 review，不猜测时长扣费；遇到网络超时或不确定结果必须查询原回执，不能盲目重复生成。

官方协议：[MiMo 音频 API](https://mimo.mi.com/docs/en-US/api/audio/tts-post)。供应商的活动价不代表本平台对用户收费价，平台以后台配置及回执快照为准。尚未配置渠道或未部署本实现时，不可将测试样例编号当作可联调的真实模型编号。

## 图片：POST /images/generations

```python
image = client.images.generate(
    model=os.environ["NOVELVIDS_IMAGE_MODEL"],
    prompt="安静的山中庭院",
    response_format="url",
)
print(image.data[0].url)
```

返回标准 ImagesResponse：created、data、usage 等；图片只在 data[].url 中返回，revised_prompt 等字段保留。客户端直接从结果 URL 下载。response_format=b64_json 和携带图片内容的流式输出不开放。上游模型通道须支持 URL 结果。

参考图生成：选择支持 URL 参考图的模型，用上传后的链接：

```python
image = client.images.generate(
    model=os.environ["NOVELVIDS_IMAGE_MODEL"],
    prompt="参考人物面部，使用剧本中的服装",
    response_format="url",
    extra_body={"image": [reference_url]},
)
```

`POST /images/edits` 接收官方 URL JSON：`model`、`prompt`、`images: [{"image_url":"https://..."}]`，可选 `mask: {"image_url":"https://..."}`。旧 `image` URL 数组仍兼容。OpenRouter 原生接口为 `POST /images`，参考图使用 `input_references: [{"type":"image_url","image_url":{"url":"https://..."}}]`。数量 n 原样传递，由上游校验；JSON 模式不接收 file_id 或内联图片。

OpenAI 兼容 GPT Image 请求可直接使用原生像素尺寸，例如 `1536x864`。平台按官方像素限制校验，不再要求尺寸出现在工作台预设白名单；像素 size 优先于额外的 aspect_ratio 提示，原样转发，不擅自改图像尺寸。两边须为 16 的倍数、最大边不超过 3840、长短边比不超过 3、总像素在 655360 至 8294400。1K/2K/4K 费用仍沿用已有短边档位及后台价格，不新增费率。URL JSON 和文件表单使用同一尺寸校验。

OpenAI 兼容图片渠道的 `/images/edits` 同时接收官方 SDK 的 multipart 文件表单：`image` / `image[]` 可传 1 至 16 张 PNG/JPEG/WebP，`mask` 可选且须为 PNG；单文件不超过 50 MiB，请求合计不超过 64 MiB。先鉴权，再解析受限文件；文件只在请求期间转发，不进入账务记录，幂等签名包含文件内容摘要。公开别名映射到供应商 model，文件请求转发到同协议的上游 `/images/edits`；不把文件请求发送给只接收 URL 的 Ark/OpenRouter 渠道。

文件编辑的 `response_format` 支持 `url`（默认）或 `b64_json`，原样保留供应商结果；Base64 模式响应上限 64 MiB。图片文件表单与 JSON 内联输入分别提交。沿用实际图片张数、参考图数、规格费率快照和一次性结算；缺少可靠计费规格时保留结果，账单待核对，不自动重提生成。

## 通用视频生成与查询

```python
video = client.videos.create(
    model=os.environ["NOVELVIDS_VIDEO_MODEL"],
    prompt="镜头沿街道缓慢前移",
    seconds="4",
    # 省略 size 时使用所选渠道的默认规格。
    extra_body={"input_reference": reference_url},
)

import time
while video.status in {"queued", "in_progress"}:
    time.sleep(3)
    video = client.videos.retrieve(video.id)
if video.status == "completed":
    content = client.videos.download_content(video.id)
    content.write_to_file("result.mp4")
else:
    print(video.error)
```

HTTPS 参考图可放在 extra_body.input_reference。文件可直接传给 SDK 的 input_reference，支持 PNG、JPEG 和 WebP。纯文生视频省略参考图。

返回标准 Video 对象：id、object="video"、model、created_at、completed_at、seconds、size、status、progress、error。`GET /videos/{id}/content` 可读取视频字节，HEAD 可读取媒体头。历史任务保留跳转下载。当前不提供 thumbnail/spritesheet。

多参考图片、视频或音频：通过 extra_body.references 传数组，元素为 {"type":"image|video|audio", "role":"reference|first_frame|last_frame", "url":"HTTPS 地址"}。input_reference 和 references 二选一。首尾帧分别提供一张图片。

工作台原有 duration、resolution、aspect_ratio 继续兼容；与 seconds、size 同时提供时须一致。

## 错误、重试与结算

上游 HTTP 错误保留原始状态码、响应体、Content-Type、Retry-After 和 X-Request-Id。平台记录错误状态与请求编号，不套猫影响应结构或改写供应商文案；回显的平台凭证会被脱敏。

平台自己的认证、权限、参数、体积和并发错误使用标准 {"error":{"message":"...","type":"...","param":null,"code":null}}。对话流开始后的错误通过 SSE 返回。

每次生成可携带唯一 Idempotency-Key。相同请求重复提交不再调用供应商或重复扣费；视频返回原任务，对话与图片返回 409 和原请求编号。修改内容使用新键。

`GET /requests/{id}` 查询平台受理与结算状态，需同一用户和团队的 Key。成功响应从 `X-Request-Id` 取平台编号。上游错误的供应商编号仍在 `X-Request-Id`，平台编号见 `X-Novelvids-Request-Id`。断线丢失平台编号时，可通过 `GET /requests?request_key=原Idempotency-Key` 恢复。已受理对话继续收集用量，并只结算一次。

`settlement.status` 为 `settled` 时，`settlement.amount` 是以 `settlement.currency` 表示的实际扣款，金额以十进制字符串返回。`pending` 表示等待结算，`review` 表示需要核对，`not_charged` 表示平台确认未扣款。这些状态的 `amount` 为空。`pricing` 是受理时的公开价格快照。

`GET /account` 返回 Key 所属的平台账户余额、币种和充值页面。打开充值页面后，使用有权为该平台团队充值的账号登录。

## 发现接口

- [完整 OpenAPI]({{BASE_URL}}/openapi.json)
- [AI 文档索引]({{BASE_URL}}/llms.txt)
- 本文可公开读取，不包含密钥。

## 原生视频、识别和增强协议（新接入优先）

下列路径可直接接在平台域名后，也可接在本文 Base URL 后（Base URL 已含 /v1）。JSON 原生参数原样传递，只将选择的模型映射到通道模型；不修改 prompt、任务 ID、状态、返回结果字段或供应商错误。鉴权使用平台 API Key，不使用供应商密钥。限流、供应商追踪等响应头保留；Cookie、认证密钥与 HTTP 逐跳／压缩头不转发。

| 供应商 | 提交 POST | 查询 GET（ASR 除外） |
| --- | --- | --- |
| 火山 Seedance | `/api/v3/contents/generations/tasks` | `/api/v3/contents/generations/tasks/{task_id}` |
| MiniMax H3 | `/v2/video_generation` | `/v2/query/video_generation/{task_id}` |
| Wan | `/api/v1/services/aigc/video-generation/video-synthesis` | `/api/v1/tasks/{task_id}` |
| AutoDL | `/api/v1/comfyui/comfyui_workflow/{model_id}` | `/api/v1/comfyui/comfyui_workflow/result/{task_id}` |
| MediaKit 增强 | `/api/v1/tools/enhance-video-generative` | `/api/v1/tasks/{task_id}` |
| SeedASR | `/api/v3/auc/bigmodel/submit` | **POST** `/api/v3/auc/bigmodel/query`，body `{}` |

有 model 的原生请求填目录的 nv-ID；没有 model 字段的协议或同名多通道，使用 `X-Cat-Model: nv-ID` 选择。AutoDL 路径中的 model_id 也可填 nv-ID。任务查询只允许任务所属用户与有对应模型权限的 Key；同一任务 ID 在多个通道冲突时，查询也须附 X-Cat-Model。

SeedASR 保留原生 user/audio/request JSON，audio.url 使用临时上传的链接。发送 `X-Api-Key: 平台Key`（也可 Authorization Bearer）、`X-Api-Resource-Id: volc.seedasr.auc`、`X-Api-Request-Id: 客户端UUID`；查询继续使用任务 ID。ASR 的 X-Api-Status-Code、X-Api-Message、X-Tt-Logid 原样保留。

MediaKit 保留 `video_url`、`resolution`、`fps`、`client_token` 等原生参数；增强计费采用结果确认的时长、分辨率与帧率。ASR 采用结果 audio_info.duration（毫秒）计费。无法确认用量则 review，不推测扣费。

平台回执 ID 在 `X-Cat-Request-Id`（兼容 X-Novelvids-Request-Id）；它与供应商任务 ID 独立。使用 `/requests/{平台回执ID}` 查询账单，任务查询仍使用原生 task_id。已计费任务重复查询不会再次扣费，通道配置变化后不会改投其他供应商查询。

```python
import uuid
import requests
headers = {"Authorization": "Bearer " + API_KEY, "X-Cat-Model": MODEL_ID}
created = requests.post(BASE_URL + "/api/v3/contents/generations/tasks", headers=headers, json={
    "model": MODEL_ID, "content": [{"type": "text", "text": "缓慢推进的镜头"}],
    "duration": 4, "resolution": "720p", "ratio": "16:9",
})
created.raise_for_status()
task_id = created.json()["id"]
result = requests.get(BASE_URL + "/api/v3/contents/generations/tasks/" + task_id, headers=headers)
result.raise_for_status()
print(result.json())  # 官方原生 status / content.video_url / usage 等字段
```
