from pydantic import BaseModel


class TemplateResponse(BaseModel):
    id: str
    name: str
    slug: str
    category: str
    description: str
    thumbnail_url: str
    usage_count: int
    rating: float


class TemplateCreateSiteRequest(BaseModel):
    template_id: str
    site_name: str

