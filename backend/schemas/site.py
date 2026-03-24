from pydantic import BaseModel


class CreateSiteRequest(BaseModel):
    site_id: str = ""
    name: str = ""
    auto_start: bool = True


class SiteResponse(BaseModel):
    site_id: str
    name: str
    status: str
    port: int | None = None
    preview_url: str
    internal_url: str


class SiteDeployConfigPayload(BaseModel):
    target_type: str = "local"
    system_api_base: str = ""
    system_id: str = ""
    app_id: str = ""
    harbor_domain: str = ""
    harbor_domain_public: str = ""
    harbor_namespace: str = ""
    module_name: str = ""
    login_tel: str = ""
    login_password: str = ""
    login_random: str = ""
    login_path: str = "/apollo/user/login"
    deploy_path: str = "/devops/cicd/v1.0/job/deployByImage"
    extra_headers_json: str = "{}"


class SiteProviderConfigPayload(BaseModel):
    codex_cmd: str = ""
    claude_cmd: str = ""
    gemini_cmd: str = ""
    codex_auth_cmd: str = ""
    claude_auth_cmd: str = ""
    gemini_auth_cmd: str = ""


class AppConfigPayload(BaseModel):
    llm_mode: str = "responses"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4.1-mini"
    codex_client_id: str = ""
    codex_client_secret: str = ""
    codex_redirect_uri: str = ""
    codex_access_token: str = ""
    codex_mcp_url: str = ""

