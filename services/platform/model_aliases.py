"""Stable readable call names, independent of prices and the legacy nv-ID permission keys."""
import re

from tortoise import Tortoise
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q
from tortoise.transactions import in_transaction
from models.config import AiModelConfig

IMAGE_NAMES = {
    'seedream_5_5':'seedream-5.5', 'seedream_5_pro':'seedream-5.0-pro',
    'seedream_5_lite':'seedream-5.0-lite', 'seedream_5_flash':'seedream-5.0-flash',
    'gpt_image_2':'gpt-image-2', 'gpt_image_2_5':'gpt-image-2.5', 'gpt_image_2_6':'gpt-image-2.6',
    'gpt_image_2_6_sunburst':'gpt-image-2.6-sunburst', 'gpt_image_2_6_flare':'gpt-image-2.6-flare',
}
VIDEO_NAMES = {
    'seedance_2':'seedance-2.0', 'seedance_2_fast':'seedance-2.0-fast',
    'seedance_2_mini':'seedance-2.0-mini', 'seedance_2_5':'seedance-2.5',
    'minimax_h3':'minimax-h3', 'minimax_h3_autodl':'minimax-h3-autodl', 'wan_3':'wan3',
}


def alias_base(config):
    base = IMAGE_NAMES.get(config.image_model_type) or VIDEO_NAMES.get(config.video_model_type)
    name = config.name.lower()
    if not base:
        if 'seed-evolving' in name:
            base = 'doubao-seed-evolving'
        elif config.api_protocol == 'volcengine_mediakit':
            base = 'mediakit-video-enhancement'
        elif config.api_protocol == 'volcengine_openspeech':
            base = 'seedasr-2.0'
        elif config.model.lower().startswith(('deepseek-', 'glm-', 'qwen-', 'gpt-', 'claude-')):
            base = config.model.lower()
        else:
            base = name
    base = re.sub(r'[^a-z0-9._-]+', '-', base).strip('-._')
    if not base or re.fullmatch(r'nv-\d+', base):
        base = {2:'image-model',4:'video-model',8:'video-enhancement',9:'speech-recognition'}.get(config.task_type,'text-model')
    if '优惠' in name or 'discount' in name:
        base += '-discount'
    return base[:160].rstrip('-._')


async def ensure_model_alias(config):
    if config.public_alias:
        return config.public_alias
    base = alias_base(config)
    attempt = 0
    while True:
        candidate = base if attempt == 0 else f'{base}-channel-{config.id}' + (f'-{attempt}' if attempt>1 else '')
        try:
            # A savepoint lets a concurrent alias collision retry without aborting model creation.
            async with in_transaction():
                if await AiModelConfig.filter(Q(public_alias=candidate) | Q(name=candidate) | Q(model=candidate)).exclude(id=config.id).exists():
                    attempt += 1
                    continue
                changed = await AiModelConfig.filter(Q(public_alias__isnull=True) | Q(public_alias=""),id=config.id).update(public_alias=candidate)
                if changed:
                    config.public_alias = candidate
                    return candidate
                latest = await AiModelConfig.get(id=config.id)
                if latest.public_alias:
                    config.public_alias = latest.public_alias
                    return latest.public_alias
        except IntegrityError:
            pass
        attempt += 1


async def ensure_model_aliases():
    db = Tortoise.get_connection('default')
    await db.execute_script('CREATE UNIQUE INDEX IF NOT EXISTS ai_model_configs_public_alias_uidx ON ai_model_configs(public_alias);')
    for config in await AiModelConfig.filter(Q(public_alias__isnull=True) | Q(public_alias="")).order_by('id'):
        await ensure_model_alias(config)
