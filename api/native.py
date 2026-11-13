"""Native provider paths, also mounted under /v1 for configurable SDK base URLs."""
from fastapi import APIRouter, Depends, Request
from auth.deps import AuthContext
from services.platform.access import developer_identity
from services.platform.http_contract import DeveloperRoute
from services.platform import native

router = APIRouter(route_class=DeveloperRoute)
NATIVE_BODY = {"requestBody":{"required":True,"content":{"application/json":{"schema":{
    "type":"object", "additionalProperties":True, "description":"供应商原生参数；媒体使用临时上传后的 HTTPS URL。用 model 或 X-Cat-Model 选择平台模型。"}}}}}


async def submit(request, ctx, protocol, model=None):
    from fastapi import HTTPException
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "请求体必须是 JSON 对象")
    return await native.submit(ctx, protocol, body, model=model,
        key=request.headers.get("idempotency-key"), incoming=request.headers)


async def query(request, ctx, identifier, protocols):
    return await native.query(ctx, identifier, protocols, incoming=request.headers, query_params=request.query_params)


@router.post("/contents/generations/tasks", openapi_extra=NATIVE_BODY)
@router.post("/api/v3/contents/generations/tasks", openapi_extra=NATIVE_BODY)
async def ark_submit(request: Request, ctx: AuthContext = Depends(developer_identity)):
    return await submit(request, ctx, "volcengine_ark")


@router.get("/contents/generations/tasks/{task_id}")
@router.get("/api/v3/contents/generations/tasks/{task_id}")
async def ark_query(task_id: str, request: Request, ctx: AuthContext = Depends(developer_identity)):
    return await query(request, ctx, task_id, ["volcengine_ark"])


@router.post("/v2/video_generation", openapi_extra=NATIVE_BODY)
async def minimax_submit(request: Request, ctx: AuthContext = Depends(developer_identity)):
    return await submit(request, ctx, "minimax")


@router.get("/v2/query/video_generation/{task_id}")
async def minimax_query(task_id: str, request: Request, ctx: AuthContext = Depends(developer_identity)):
    return await query(request, ctx, task_id, ["minimax"])


@router.post("/api/v1/services/aigc/video-generation/video-synthesis", openapi_extra=NATIVE_BODY)
async def wan_submit(request: Request, ctx: AuthContext = Depends(developer_identity)):
    return await submit(request, ctx, "dashscope")


@router.get("/api/v1/tasks/{task_id}")
async def cloud_task(task_id: str, request: Request, ctx: AuthContext = Depends(developer_identity)):
    return await query(request, ctx, task_id, ["dashscope", "volcengine_mediakit"])


@router.get("/api/v1/comfyui/comfyui_workflow/result/{task_id}")
async def autodl_query(task_id: str, request: Request, ctx: AuthContext = Depends(developer_identity)):
    return await query(request, ctx, task_id, ["autodl"])


@router.post("/api/v1/comfyui/comfyui_workflow/{workflow_id}", openapi_extra=NATIVE_BODY)
async def autodl_submit(workflow_id: str, request: Request, ctx: AuthContext = Depends(developer_identity)):
    return await submit(request, ctx, "autodl", workflow_id)


@router.post("/api/v1/tools/enhance-video-generative", openapi_extra=NATIVE_BODY)
async def enhancement_submit(request: Request, ctx: AuthContext = Depends(developer_identity)):
    return await submit(request, ctx, "volcengine_mediakit", "enhance-video-generative")


@router.post("/api/v3/auc/bigmodel/submit", openapi_extra=NATIVE_BODY)
async def asr_submit(request: Request, ctx: AuthContext = Depends(developer_identity)):
    return await submit(request, ctx, "volcengine_openspeech")


@router.post("/api/v3/auc/bigmodel/query", openapi_extra=NATIVE_BODY)
async def asr_query(request: Request, ctx: AuthContext = Depends(developer_identity)):
    from fastapi import HTTPException
    identifier = request.headers.get("x-api-request-id")
    if not identifier:
        raise HTTPException(400, "缺少 X-Api-Request-Id")
    return await query(request, ctx, identifier, ["volcengine_openspeech"])


from services.platform.images import ImageRequest, generate as generate_image


@router.post("/api/v3/images/generations", summary="Seedream 原生 URL 图片生成")
async def seedream_images(body: ImageRequest, request: Request, ctx: AuthContext = Depends(developer_identity)):
    return await generate_image(ctx, body, request.headers.get("idempotency-key"), protocol="volcengine_ark")
