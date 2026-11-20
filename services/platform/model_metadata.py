"""Public model identifiers and OpenRouter-style modality metadata, without private routes."""
from services.platform.model_aliases import IMAGE_NAMES, VIDEO_NAMES


def model_identifier(row):
    model = row['model']
    if row.get('video_model_type') == 'minimax_h3_autodl':
        return 'minimax-h3'
    if model.startswith('ep-'):
        if row.get('image_model_type') in IMAGE_NAMES:
            return IMAGE_NAMES[row['image_model_type']]
        if row.get('video_model_type') in VIDEO_NAMES:
            return VIDEO_NAMES[row['video_model_type']]
        if 'seed-evolving' in row['name'].lower():
            return 'doubao-seed-evolving'
        return None  # An opaque endpoint does not establish the underlying public model.
    return model


def modality_metadata(row, kinds):
    inputs, outputs, endpoints = [], [], []
    for kind in kinds:
        incoming, outgoing = {
            'text':(['text'], ['text']), 'image':(['text', 'image'], ['image']),
            'video':(['text', 'image'], ['video']), 'asr':(['audio'], ['text']),
            'media_processing':(['video'], ['video']), 'voice_design':(['text'], ['audio']),
        }[kind]
        if kind == 'text' and row.get('model_id') == 'doubao-seed-evolving':
            incoming = ['text', 'image', 'video']
        if kind == "text" and row.get("text_input_modalities"):
            incoming = row["text_input_modalities"]
        inputs.extend(incoming);outputs.extend(outgoing)
        if kind == 'text':
            endpoints.append('/v1/responses' if row['text_api']=='responses' else '/v1/chat/completions')
        elif kind == 'image':
            endpoints.append('/v1/images/generations')
            if row.get('reference_image_urls'):
                endpoints.append('/v1/images/edits')
        elif kind == 'voice_design':
            endpoints.append('/v1/chat/completions')
        elif kind == 'video':
            endpoints.append('/v1/videos')
    native = row.get('native_api')
    if native:
        endpoints.append('/v1' + native['submit'])
    inputs, outputs = list(dict.fromkeys(inputs)), list(dict.fromkeys(outputs))
    parameters = []
    if row['tool_calls']:
        parameters.extend(['tools', 'tool_choice'])
    if row['json_output']:
        parameters.append('response_format')
    return {'architecture':{'input_modalities':inputs,'output_modalities':outputs,
                           'modality':'+'.join(inputs)+'->'+'+'.join(outputs)},
            'input_modalities':inputs,'output_modalities':outputs,'endpoints':list(dict.fromkeys(endpoints)),
            'supported_parameters':parameters}


def public_models(rows):
    """Expose existing callable aliases, preserving channel identity and published prices."""
    seen = set()
    output = []
    for row in rows:
        identifier = row.get('alias') or row.get('model_id')
        if not identifier or identifier in seen:
            continue
        seen.add(identifier)
        output.append({**{k:v for k,v in row.items() if k not in {'alias','model_id'}},
                       'legacy_id':row['id'], 'id':identifier, 'name':identifier})
    return output
