"""Public documentation metadata; external pages never receive a platform credential."""
from ipaddress import ip_address
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, Field, HttpUrl, TypeAdapter, field_validator
from models.config import GeneralConfig
from config import settings


class DocumentationSettings(BaseModel):
    url: str = Field(default="", max_length=2048)

    @field_validator("url")
    @classmethod
    def public_url(cls, value):
        value = value.strip()
        if not value:
            return ""
        parsed = TypeAdapter(HttpUrl).validate_python(value)
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise ValueError("请填写不含账号密码的公开 HTTPS 文档链接")
        host = parsed.host or ""
        try:
            private = not ip_address(host.strip("[]")).is_global
        except ValueError:
            private = "." not in host or host.endswith((".local", ".localhost", ".internal"))
        if private:
            raise ValueError("请填写公开文档地址")
        if any(key.lower() in {"token", "access_token", "api_key", "key", "password", "authorization"}
               for key, _ in parse_qsl(parsed.query or "")):
            raise ValueError("公开文档链接不能包含密钥或访问密码")
        return str(parsed)


async def documentation_settings():
    row = await GeneralConfig.filter(id=1).first()
    value = row.api_docs_url if row and row.api_docs_url is not None else settings.API_DOCUMENTATION_URL
    return DocumentationSettings(url=value)


async def update_documentation(body):
    row, _ = await GeneralConfig.get_or_create(id=1)
    await GeneralConfig.filter(id=row.id).update(api_docs_url=body.url)
    return body


async def documentation_origin():
    try:
        value = (await documentation_settings()).url
    except Exception:
        # Headers must also work on startup/health failures before the ORM is available.
        try:
            value = DocumentationSettings(url=settings.API_DOCUMENTATION_URL).url
        except ValueError:
            value = ""
    parsed = urlsplit(value)
    return f"{parsed.scheme}://{parsed.netloc}" if value else ""


def with_documentation_frame(policy, origin):
    if not origin:
        return policy
    directives = [part.strip() for part in policy.split(";") if part.strip()]
    for index, part in enumerate(directives):
        values = part.split()
        if values[0].lower() == "frame-src":
            sources = [v for v in values[1:] if v != "'none'"]
            if origin not in sources:
                sources.append(origin)
            directives[index] = "frame-src " + " ".join(sources)
            break
    else:
        # Keep default-src fallback sources when adding this one specific frame origin.
        default = next((part.split()[1:] for part in directives if part.startswith("default-src ")), [])
        directives.append("frame-src " + " ".join([v for v in default if v != "'none'"] + [origin]))
    return "; ".join(directives) + ";"
