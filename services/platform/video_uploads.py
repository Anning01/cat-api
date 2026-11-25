from services.platform.temporary_media import store_input


async def store_video_reference(user_id, image):
    _, data, mime = image
    return await store_input(user_id, data, mime)
