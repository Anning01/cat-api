"""Importable public API contract. No runtime model records, credentials or console routes are exported."""
from copy import deepcopy
from fastapi.openapi.utils import get_openapi
from config import settings


def obj(properties=None, required=(), description=None):
    value = {"type":"object", "properties":properties or {}, "additionalProperties":True}
    if required:
        value["required"] = list(required)
    if description:
        value["description"] = description
    return value


def ref(name):
    return {"$ref":"#/components/schemas/"+name}


def string(description="", **extra):
    return {"type":"string", **({"description":description} if description else {}), **extra}


def array(item):
    return {"type":"array", "items":item}


def parameter(name, description, *, required=False, location="header", schema=None, example=None):
    value = {"name":name,"in":location,"required":required,"description":description,"schema":schema or {"type":"string"}}
    if example is not None:
        value["example"] = example
    return value


DESCRIPTION = """Cat API 模型开放平台。供应商原生请求与结果按原格式转发，仅进行鉴权、模型路由、任务归属与计费。

**媒体规则**：先调用 `/media/uploads` 申请临时直传，文件直接 PUT 到 OSS，再把 `read_url` 放入生成请求。平台不接收 multipart、Base64 文件、data URL、内联音频或文件；不开放携带内联媒体的图片流式输出。MD5 摘要的 Base64 编码不属于文件内容。

**身份与编号**：平台 Key 填入 Bearer；部分原生协议也支持对应鉴权头。使用目录 `nv-ID` 或 `X-Cat-Model` 选择通道。供应商 `X-Request-Id` 和任务 ID 保留，平台账务 UUID 位于 `X-Cat-Request-Id`（兼容 `X-Novelvids-Request-Id`）。

**计费**：成功结果不因计费暂时失败而被替换。使用 `/requests` 查询 pending、settled、review、not_charged。平台金额包含折扣，不能重复打折。Seedream 5.5/5.0 Pro 可按 pixel_tier 与实际输出档位计费，模型与价格以运行环境 `/models` 为准。

**接入**：新供应商任务使用原生路径；历史 `/videos` 保留统一格式兼容，不是供应商原生返回。原生路径在平台根地址和本文件 server `/v1` 下均可使用。示例模型 ID、URL 与任务 ID 仅供导入和阅读，不代表真实可用配置。"""


OPERATIONS = {
    ("/models","get"):("listModels","模型与账户","查询已授权模型、能力与价格","ModelList"),
    ("/account","get"):("getAccount","模型与账户","查询 Key 所属账户余额","PlatformAccountOut"),
    ("/chat/completions","post"):("createChatCompletion","文本对话","创建对话／SSE 流式输出","ChatCompletion"),
    ("/images/generations","post"):("generateImages","图片生成","生成 URL 图片","ImageResult"),
    ("/images/edits","post"):("editImages","图片生成","使用临时上传 URL 编辑图片","ImageResult"),
    ("/api/v3/images/generations","post"):("generateSeedreamImages","图片/Seedream","Seedream 5.5／5.0 Pro URL 图片生成","ImageResult"),
    ("/images","post"):("generateOpenRouterImages","图片生成","OpenRouter 原生 URL 图片接口","ImageResult"),
    ("/media/uploads","post"):("createTemporaryUpload","临时素材","申请 OSS 临时直传票据","UploadTicket"),
    ("/requests","get"):("getReceiptByKey","调用与结算","按原幂等键查询回执","PlatformReceiptOut"),
    ("/requests/{request_id}","get"):("getReceipt","调用与结算","按平台 UUID 查询回执","PlatformReceiptOut"),
    ("/videos","post"):("createLegacyVideo","视频兼容","提交历史统一视频任务","LegacyVideo"),
    ("/videos/{identifier}","get"):("getLegacyVideo","视频兼容","查询历史统一任务及结果 URL","LegacyVideo"),
    ("/videos/{identifier}/content","get"):("downloadLegacyVideo","视频兼容","跳转下载已完成的视频",None),
    ("/api/v3/contents/generations/tasks","post"):("createSeedanceTask","Seedance","提交 Seedance 原生任务","ArkTask"),
    ("/api/v3/contents/generations/tasks/{task_id}","get"):("getSeedanceTask","Seedance","查询 Seedance 原生结果","ArkTask"),
    ("/v2/video_generation","post"):("createMiniMaxTask","MiniMax","提交 MiniMax H3 原生任务","MiniMaxTask"),
    ("/v2/query/video_generation/{task_id}","get"):("getMiniMaxTask","MiniMax","查询 MiniMax 原生结果","MiniMaxTask"),
    ("/api/v1/services/aigc/video-generation/video-synthesis","post"):("createWanTask","Wan","提交 Wan 原生视频任务","WanTask"),
    ("/api/v1/tasks/{task_id}","get"):("getCloudTask","Wan 与 MediaKit","查询当前账户的 Wan／MediaKit 任务","CloudTask"),
    ("/api/v1/comfyui/comfyui_workflow/{workflow_id}","post"):("createAutoDLTask","AutoDL","提交 AutoDL 原生工作流","AutoDLTask"),
    ("/api/v1/comfyui/comfyui_workflow/result/{task_id}","get"):("getAutoDLTask","AutoDL","查询 AutoDL 原生结果","AutoDLTask"),
    ("/api/v1/tools/enhance-video-generative","post"):("createEnhancementTask","MediaKit","提交画质增强原生任务","MediaKitTask"),
    ("/api/v3/auc/bigmodel/submit","post"):("createTranscriptionTask","SeedASR","提交 URL 音频识别任务","ASRResult"),
    ("/api/v3/auc/bigmodel/query","post"):("getTranscriptionTask","SeedASR","查询识别结果与实际音频时长","ASRResult"),
}


def public_openapi(app):
    document = get_openapi(title="Cat API · 模型开放平台", version="1.1.0", description=DESCRIPTION,
                           routes=app.routes, openapi_version="3.1.0")
    document["servers"] = [{"url":settings.PUBLIC_API_BASE_URL or "/v1", "description":"Cat API 服务地址；导入 Apifox 后可配置测试／生产环境"}]
    components = document.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    url = string("临时上传后可访问的 HTTPS URL；不接受 data URL", format="uri", pattern="^https://")
    number = {"type":"number", "minimum":0}
    integer = {"type":"integer", "minimum":0}
    usage = obj({"prompt_tokens":integer,"completion_tokens":integer,"total_tokens":integer}, description="供应商实际报告用量及扩展字段；字段不强制裁剪")
    pricing = obj({"type":string(),"currency":string(enum=["CNY"]),"billing_unit":string(enum=["token","second","minute","pixel_tier"]),
        "discount":number,"prices":{"type":"object","additionalProperties":number},
        "input_image":obj({"first_free":integer,"price_per_image":number}),"tiers":array(obj({"short_side_max":integer,"fps_max":number,"price":number})),
        "input_price_per_1m":number,"output_price_per_1m":number,"cache_input_price_per_1m":number,"price_per_minute":number})
    model = obj({"id":string("兼容模式为 nv-ID；identifier=alias 模式为可读调用名"),
        "alias":{"type":["string","null"],"description":"推荐用于 model 的稳定可读调用名","examples":["seedream-5.5"]},
        "legacy_id":string("兼容和授权使用的配置 ID",pattern=r"^nv-[1-9][0-9]{0,9}$"),"object":string(),"owned_by":string(),"name":string(),"created":integer,
        "kinds":array(string()),"task_types":array(integer),"image_model_type":{"type":["string","null"],"examples":["seedream_5_5"]},
        "video_model_type":{"type":["string","null"]},"pricing":pricing,"concurrency":integer,"tool_calls":{"type":"boolean"},
        "json_output":{"type":"boolean"},"reference_image_urls":{"type":"boolean"},
        "native_api":obj({"submit":string(),"query":string()})}, required=["id","name","pricing"])
    schemas.update({
        "PlatformError":obj({"error":obj({"message":string(),"type":string(),"param":{"type":["string","null"]},"code":{"type":["string","null"]}})},required=["error"]),
        "ModelList":obj({"object":string(enum=["list"]),"data":array(model)},required=["object","data"]),
        "ChatCompletion":obj({"id":string(),"object":string(),"created":integer,"model":string("供应商原始模型标识，不保证等于请求的 nv-ID"),
            "choices":array(obj({"index":integer,"message":obj({"role":string(),"content":{"type":["string","null"]},"tool_calls":array(obj()),"reasoning_content":string()}),
                "finish_reason":{"type":["string","null"]}})),"usage":usage}),
        "ImageResult":obj({"created":integer,"data":array(obj({"url":url,"size":string(),"revised_prompt":string(),"error":obj()})),
            "images":array({"anyOf":[url,obj({"url":url})]}),"usage":obj()},description="供应商 URL 图片结果及原生扩展字段。平台不新增 data 包装、不接收 b64_json。"),
        "UploadTicket":obj({"media_id":integer,"upload_url":url,"headers":{"type":"object","additionalProperties":{"type":"string"}},
            "read_url":url,"expires_at":integer},required=["media_id","upload_url","headers","read_url","expires_at"]),
        "LegacyVideo":obj({"id":string(format="uuid"),"object":string(enum=["video"]),"model":string(),"status":string(enum=["queued","in_progress","completed","failed"]),
            "progress":integer,"created_at":integer,"completed_at":{"type":["integer","null"]},"seconds":string(),"size":string(),"error":{"type":["object","null"]},
            "metadata":{"type":["object","null"],"properties":{"url":url,"last_frame_url":url,"duration":number}},"billing_status":string()}),
        "ArkTask":obj({"id":string(),"model":string(),"status":string(enum=["queued","running","cancelled","succeeded","failed","expired"]),
            "content":obj({"video_url":url,"last_frame_url":url}),"usage":usage,"duration":integer,"resolution":string(),"error":{"type":["object","null"]}}),
        "MiniMaxTask":obj({"task_id":string(),"status":string(),"base_resp":obj({"status_code":integer,"status_msg":string()}),"video_url":url,"usage":obj(),"content":obj()}),
        "WanTask":obj({"request_id":string(),"output":obj({"task_id":string(),"task_status":string(),"video_url":url,"code":string(),"message":string()}),"usage":obj(),"code":string(),"message":string()}),
        "AutoDLTask":obj({"code":{"type":["string","integer"]},"msg":string(),"request_id":string(),"data":obj({"task_id":string(),"status":string(),"workflow":string(),"results":array(obj({"type":string(),"url":url}))})}),
        "MediaKitTask":obj({"success":{"type":"boolean"},"task_id":string(),"status":string(),"request_id":string(),"expires_at":integer,
            "result":obj({"video_url":url,"duration":number,"fps":number,"resolution":string()}),"error":{"type":["object","null"]}}),
        "ASRResult":obj({"task_id":string(),"audio_info":obj({"duration":{**integer,"description":"实际音频时长，毫秒"}}),
            "result":obj({"text":string(),"utterances":array(obj({"text":string(),"start_time":integer,"end_time":integer,"words":array(obj())}))})},
            description="识别状态主要位于 X-Api-Status-Code／X-Api-Message 响应头；提交成功正文可为空对象。"),
    })
    schemas["CloudTask"] = {"anyOf":[ref("WanTask"),ref("MediaKitTask")]}
    # Native request bodies remain open to vendor extensions; these describe common official fields.
    content = array(obj({"type":string(),"text":string(),"image_url":obj({"url":url}),"video_url":obj({"url":url}),
        "audio_url":obj({"url":url}),"role":string(),"draft_task":obj({"id":string()})},required=["type"]))
    video_request = obj({"model":string("模型目录中的 nv-ID 或唯一模型别名"),"content":content,"duration":{"type":"integer"},
        "resolution":string(),"ratio":string(),"seed":{"type":"integer"},"generate_audio":{"type":"boolean"},
        "return_last_frame":{"type":"boolean"},"watermark":{"type":"boolean"}},required=["model","content"])
    request_bodies = {
        "/api/v3/contents/generations/tasks":("SeedanceRequest",video_request),
        "/v2/video_generation":("MiniMaxRequest",{**video_request,"properties":{**video_request["properties"],"aigc_watermark":{"type":"boolean"}}}),
        "/api/v1/services/aigc/video-generation/video-synthesis":("WanRequest",obj({"model":string(),"input":obj({"prompt":string(),"media":content}),
            "parameters":obj({"duration":{"type":"integer"},"resolution":string(),"ratio":string(),"seed":{"type":"integer"}})},required=["model","input"])),
        "/api/v1/comfyui/comfyui_workflow/{workflow_id}":("AutoDLRequest",obj({"prompt":string(),"duration":{"type":"integer"},"resolution":string(),"ref_image_0":url,"ref_audio_0":url},description="保留所选工作流的参数，具体字段由工作流定义。")),
        "/api/v1/tools/enhance-video-generative":("EnhancementRequest",obj({"video_url":url,"resolution":string(),"fps":number,"client_token":string(),"queue_id":string()},required=["video_url"])),
        "/api/v3/auc/bigmodel/submit":("ASRRequest",obj({"user":obj({"uid":string()}),"audio":obj({"url":url,"format":string()},required=["url"]),
            "request":obj({"model_name":string(),"enable_itn":{"type":"boolean"},"enable_punc":{"type":"boolean"},"show_utterances":{"type":"boolean"}})},required=["audio"])),
        "/api/v3/auc/bigmodel/query":("ASRQuery",obj()),
    }
    components["securitySchemes"] = {
        "PlatformKey":{"type":"http","scheme":"bearer","bearerFormat":"Cat API Key","description":"使用平台签发的 Key；不要填写供应商密钥，也不要公开真实 Key。"},
        "SeedASRKey":{"type":"apiKey","in":"header","name":"X-Api-Key","description":"SeedASR 原生鉴权形状，此处填写平台 Key。"},
        "AutoDLKey":{"type":"apiKey","in":"header","name":"Authorization","description":"AutoDL 原生形状，直接填写平台 Key；也支持 Bearer。"},
    }
    document["security"] = [{"PlatformKey":[]}]
    headers = {name:{"description":description,"schema":{"type":"string"}} for name,description in {
        "X-Cat-Request-Id":"平台回执 UUID，用于 /requests/{request_id} 查询账单。",
        "X-Novelvids-Request-Id":"兼容旧客户端的平台回执 UUID。",
        "X-Request-Id":"供应商原始追踪编号；未提供时才使用平台编号，不保证是 UUID。",
        "Retry-After":"并发／限流时的建议重试间隔。",
    }.items()}
    for path in list(document["paths"]):
        if path.startswith("/contents/"):
            del document["paths"][path]  # Alias remains callable, but isn't duplicated in imported docs.
    folders = {"模型与账户":"公共能力/模型与账户", "文本对话":"LLM/对话与流式输出", "图片生成":"图片/OpenAI 兼容",
        "临时素材":"公共能力/临时上传", "调用与结算":"公共能力/调用与结算", "视频兼容":"兼容接口/历史视频",
        "Seedance":"视频/Seedance", "MiniMax":"视频/MiniMax", "Wan":"视频/Wan3", "Wan 与 MediaKit":"视频/Wan3",
        "AutoDL":"视频/AutoDL", "MediaKit":"视频/画质增强", "SeedASR":"音频/SeedASR"}
    for (path, method), (identifier, tag, title, result_schema) in OPERATIONS.items():
        operation = document["paths"][path][method]
        folder = "图片/OpenRouter" if path == "/images" else folders.get(tag, tag)
        operation.update(operationId=identifier,tags=[folder],summary=title,security=[{"PlatformKey":[]}])
        operation["x-apifox-folder"] = folder
        operation["description"] = "原生扩展字段保留。平台生成接口只接收不超过 1 MB 的 JSON 与媒体 HTTPS URL；不接收 Base64 或 multipart。"
        if tag == "视频兼容":
            operation["description"] = "历史统一格式兼容入口，保留平台 UUID、completed 与 metadata.url；新供应商接入优先使用原生任务接口。"
        parameters = operation.setdefault("parameters", [])
        if method == "post":
            if not any(p.get("name", "").lower()=="idempotency-key" for p in parameters):
                parameters.append(parameter("Idempotency-Key","每次逻辑调用的唯一标识；不确定是否受理时先查回执，不换键盲目重试。"))
        if path in request_bodies:
            name, schema = request_bodies[path]
            schemas[name] = deepcopy(schema)
            operation["requestBody"] = {"required":True,"content":{"application/json":{"schema":ref(name)}}}
        if any(value in path for value in ("/api/", "/v2/")):
            parameters.append(parameter("X-Cat-Model","选择模型目录 nv-ID；无 model 字段或同名多通道时需要填写。",example="nv-42"))
        if "/auc/bigmodel/" in path:
            operation["security"] = [{"PlatformKey":[]},{"SeedASRKey":[]}]
            parameters.extend([parameter("X-Api-Request-Id","提交和查询使用同一个任务 ID。",required=True,example="11111111-1111-4111-8111-111111111111"),
                parameter("X-Api-Resource-Id","对应模型资源 ID；使用 X-Cat-Model 选通道时仍可填写原生资源 ID。",example="volc.seedasr.auc"),
                parameter("X-Api-Sequence","提交时的原生发包序号。",example="-1")])
        if "/comfyui_workflow/" in path:
            operation["security"] = [{"PlatformKey":[]},{"AutoDLKey":[]}]
        if "video-synthesis" in path:
            parameters.append(parameter("X-DashScope-Async","原生异步提交头，平台会设置 enable。",example="enable"))
        responses = operation.setdefault("responses", {})
        if result_schema:
            responses["200"] = {"description":"成功结果按上游结构保留；HTTP 200 也可能携带供应商业务错误，请同时检查正文及状态头。",
                "headers":deepcopy(headers),"content":{"application/json":{"schema":ref(result_schema)}}}
        else:
            responses.pop("200", None)
            responses["307"] = {"description":"跳转至供应商视频下载地址，不通过平台转发视频文件。",
                "headers":{"Location":{"description":"成片 URL","schema":url},**deepcopy(headers)}}
        if path == "/chat/completions":
            responses["200"]["content"]["text/event-stream"] = {"schema":string("上游 SSE 原始事件，保留心跳、扩展字段和 [DONE]；需要计费用量时显式发送 include_usage=true。"),
                "example":'data: {"id":"chatcmpl-example","object":"chat.completion.chunk","model":"vendor-model","choices":[{"index":0,"delta":{"content":"你好"}}]}\n\ndata: [DONE]\n\n'}
        if "/auc/bigmodel/" in path:
            responses["200"]["headers"].update({name:{"schema":{"type":"string"},"description":description} for name,description in {
                "X-Api-Status-Code":"20000000 成功；20000001 处理中；20000002 排队中；其他状态保留供应商值。",
                "X-Api-Message":"供应商状态说明。","X-Tt-Logid":"供应商追踪 ID。"}.items()})
        for code, description in {400:"请求参数或媒体模式不支持",401:"平台 Key 缺失、无效或到期",402:"账户余额不足",403:"账户／模型权限不足",404:"模型或当前账户任务不存在",409:"幂等冲突、任务标识冲突或通道已变化",413:"JSON 请求超过大小限制",422:"字段、URL 或价格配置不符合要求",429:"并发／限流",500:"内部错误",502:"上游结果不确定、网络异常或返回了禁止的内联媒体",503:"服务或临时存储不可用"}.items():
            responses[str(code)] = {"description":description+"；供应商的错误正文与状态码保留，error 对象是平台错误示例，不强制包装供应商错误。", "headers":deepcopy(headers),
                "content":{"application/json":{"schema":obj({"error":obj({"message":string(),"type":string(),"param":{},"code":{}})}),
                    "example":{"error":{"message":description,"type":"invalid_request_error" if code<500 else "server_error","param":None,"code":None}}},
                    "text/plain":{"schema":{"type":"string"}}}}
    request_examples = {
        "/chat/completions":{"非流式":{"value":{"model":"nv-42","messages":[{"role":"user","content":"你好"}]}},
            "流式与用量":{"value":{"model":"nv-42","messages":[{"role":"user","content":"你好"}],"stream":True,"stream_options":{"include_usage":True}}}},
        "/images/generations":{"URL 图片":{"value":{"model":"nv-42","prompt":"山中庭院","size":"1024x1024","n":1,"response_format":"url"}}},
        "/api/v3/images/generations":{"Seedream 5.5":{"value":{"model":"nv-42","prompt":"保持参考图人物特征","size":"2048x1152","image":["https://cdn.example/reference.png"],"n":1,"response_format":"url"}}},
        "/images/edits":{"URL 参考图与蒙版":{"value":{"model":"nv-42","prompt":"更换背景","images":[{"image_url":"https://cdn.example/reference.png"}],"mask":{"image_url":"https://cdn.example/mask.png"},"response_format":"url"}}},
        "/images":{"OpenRouter URL 参考图":{"value":{"model":"nv-42","prompt":"山中庭院","input_references":[{"type":"image_url","image_url":{"url":"https://cdn.example/reference.png"}}],"n":1,"response_format":"url"}}},
        "/media/uploads":{"申请图片直传":{"value":{"content_type":"image/png","byte_length":12345,"content_md5":"1B2M2Y8AsgTpgAmY7PhCfg=="}}},
        "/videos":{"历史兼容请求":{"value":{"model":"nv-42","prompt":"缓慢推进的镜头","seconds":"4","size":"1280x720"}}},
        "/api/v3/contents/generations/tasks":{"文生视频":{"value":{"model":"nv-42","content":[{"type":"text","text":"缓慢推进的镜头"}],"duration":4,"resolution":"720p","ratio":"16:9"}}},
        "/v2/video_generation":{"MiniMax H3":{"value":{"model":"nv-42","content":[{"type":"text","text":"缓慢推进的镜头"}],"duration":6,"resolution":"768P","ratio":"16:9"}}},
        "/api/v1/services/aigc/video-generation/video-synthesis":{"Wan3":{"value":{"model":"nv-42","input":{"prompt":"缓慢推进的镜头"},"parameters":{"duration":5,"resolution":"720p","ratio":"16:9"}}}},
        "/api/v1/comfyui/comfyui_workflow/{workflow_id}":{"工作流参数":{"value":{"prompt":"缓慢推进的镜头","duration":6,"resolution":"768P"}}},
        "/api/v1/tools/enhance-video-generative":{"画质增强":{"value":{"video_url":"https://cdn.example/source.mp4","resolution":"1080p","fps":30,"client_token":"example-client-request"}}},
        "/api/v3/auc/bigmodel/submit":{"URL 音频":{"value":{"user":{"uid":"example-user"},"audio":{"url":"https://cdn.example/audio.mp3","format":"mp3"},"request":{"model_name":"bigmodel","show_utterances":True}}}},
        "/api/v3/auc/bigmodel/query":{"查询原任务":{"value":{}}},
    }
    result_examples = {
        "ModelList":{"object":"list","data":[{"id":"nv-42","name":"Seedream 5.5","kinds":["image"],"task_types":[2],"image_model_type":"seedream_5_5", "pricing":{"type":"image","currency":"CNY","billing_unit":"pixel_tier","prices":{"low":0.13,"high_capped":0.23},"input_image":{"first_free":0,"price_per_image":0.05},"discount":1}}]},
        "PlatformAccountOut":{"balance":"100.000000","currency":"CNY","recharge_url":"https://api.example.com/#/profile?recharge=1"},
        "ChatCompletion":{"id":"chatcmpl-example","object":"chat.completion","created":1700000000,"model":"vendor-model","choices":[{"index":0,"message":{"role":"assistant","content":"你好"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}},
        "ImageResult":{"created":1700000000,"data":[{"url":"https://cdn.example/result.png","size":"2048x1152"}]},
        "UploadTicket":{"media_id":1,"upload_url":"https://upload.example/reference.png","headers":{"content-type":"image/png","content-length":"12345","content-md5":"1B2M2Y8AsgTpgAmY7PhCfg=="},"read_url":"https://cdn.example/reference.png","expires_at":1700172800},
        "PlatformReceiptOut":{"id":"11111111-1111-4111-8111-111111111111","model":"nv-42","status":"completed","usage":{"image_count":1,"input_image_count":2,"output_tier_counts":{"low":1}},"settlement":{"status":"settled","amount":"0.230000","currency":"CNY"},"pricing":{"type":"image","billing_unit":"pixel_tier","currency":"CNY","prices":{"low":0.13,"high_capped":0.23},"input_image":{"first_free":0,"price_per_image":0.05}}},
        "LegacyVideo":{"id":"11111111-1111-4111-8111-111111111111","object":"video","model":"nv-42","status":"queued","progress":0,"created_at":1700000000,"completed_at":None,"seconds":"4","size":"1280x720","error":None},
        "ArkTask":{"id":"cgt-example","model":"vendor-model","status":"succeeded","content":{"video_url":"https://cdn.example/video.mp4"},"duration":4,"resolution":"720p","usage":{"completion_tokens":100}},
        "MiniMaxTask":{"task_id":"example-task","status":"succeeded","video_url":"https://cdn.example/video.mp4","base_resp":{"status_code":0,"status_msg":"success"}},
        "WanTask":{"request_id":"provider-trace","output":{"task_id":"example-task","task_status":"SUCCEEDED","video_url":"https://cdn.example/video.mp4"},"usage":{"output_video_duration":5}},
        "CloudTask":{"success":True,"task_id":"example-task","status":"completed","result":{"video_url":"https://cdn.example/video.mp4","duration":60,"fps":30,"resolution":"1080p"}},
        "AutoDLTask":{"code":"Success","msg":"","data":{"task_id":"example-task","status":"SUCCESS","results":[{"type":"video","url":"https://cdn.example/video.mp4"}]}},
        "MediaKitTask":{"success":True,"task_id":"example-task","status":"completed","result":{"video_url":"https://cdn.example/video.mp4","duration":60,"fps":30,"resolution":"1080p"}},
        "ASRResult":{"audio_info":{"duration":60000},"result":{"text":"识别结果","utterances":[{"text":"识别结果","start_time":0,"end_time":60000}]}},
    }
    for (path, method), (_, _, _, name) in OPERATIONS.items():
        operation = document["paths"][path][method]
        if path in request_examples:
            operation["requestBody"]["content"]["application/json"]["examples"] = deepcopy(request_examples[path])
        if name:
            operation["responses"]["200"]["content"]["application/json"]["example"] = deepcopy(result_examples[name])
        if method == "post" and path in request_examples:
            example_alias = "deepseek-flash" if path == "/chat/completions" else "seedance-2.0" if path in {"/videos","/api/v3/contents/generations/tasks"} else "minimax-h3" if path == "/v2/video_generation" else "wan3" if "video-synthesis" in path else "seedream-5.5" if path == "/api/v3/images/generations" else "gpt-image-2-discount"
            for sample in operation["requestBody"]["content"]["application/json"]["examples"].values():
                if "model" in sample["value"]:
                    sample["value"]["model"] = example_alias
        if path == "/models":
            operation["description"] += " 默认兼容 nv-ID。新软件可使用 identifier=alias，让 data[].id 为可读调用名；legacy_id 保留授权与历史关联 ID。两种视图按同一 Key 模型权限过滤。"
            operation["responses"]["200"]["content"]["application/json"]["example"]["data"][0].update(alias="seedream-5.5",legacy_id="nv-42")
        if path == "/api/v3/auc/bigmodel/submit":
            operation["responses"]["200"]["content"]["application/json"]["example"] = {}
        if path == "/api/v1/tasks/{task_id}":
            operation["description"] += " 此路径也用于 MediaKit 画质增强查询，由任务归属自动选择通道；无需创建重复接口。"
        if path in {"/images/generations","/images/edits"}:
            operation["description"] += " 此目录按 OpenAI 兼容形状展示；原通用入口仍可用 model 路由其他图片通道。Seedream 和 OpenRouter 各有独立原生入口。"
    submitted_examples = {
        "/api/v3/contents/generations/tasks":{"id":"cgt-example"},
        "/v2/video_generation":{"task_id":"example-task","base_resp":{"status_code":0,"status_msg":"success"}},
        "/api/v1/services/aigc/video-generation/video-synthesis":{"request_id":"provider-trace","output":{"task_id":"example-task","task_status":"PENDING"}},
        "/api/v1/comfyui/comfyui_workflow/{workflow_id}":{"code":"Success","msg":"","data":{"task_id":"example-task","status":"QUEUED"}},
        "/api/v1/tools/enhance-video-generative":{"success":True,"task_id":"example-task","request_id":"provider-trace"},
    }
    for path,example in submitted_examples.items():
        document["paths"][path]["post"]["responses"]["200"]["content"]["application/json"]["example"] = example
    document["paths"]["/videos/{identifier}"]["get"]["responses"]["200"]["content"]["application/json"]["example"] = {
        **result_examples["LegacyVideo"], "status":"completed", "progress":100, "completed_at":1700000100,
        "metadata":{"url":"https://cdn.example/video.mp4","duration":4}, "billing_status":"completed"}
    ordered_folders = ["视频/Seedance","视频/MiniMax","视频/Wan3","视频/AutoDL","视频/画质增强",
        "图片/Seedream","图片/OpenAI 兼容","图片/OpenRouter","LLM/对话与流式输出","音频/SeedASR",
        "公共能力/模型与账户","公共能力/临时上传","公共能力/调用与结算","兼容接口/历史视频"]
    document["tags"] = [{"name":folder} for folder in ordered_folders]
    rank = {name:index for index,name in enumerate(ordered_folders)}
    document["paths"] = dict(sorted(document["paths"].items(), key=lambda pair: min(rank[op["x-apifox-folder"]] for op in pair[1].values())))
    return document
