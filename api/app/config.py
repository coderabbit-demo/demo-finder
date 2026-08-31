from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./demo.db"
    github_token: str = ""
    anthropic_api_key: str = ""
    dev_mode: bool = False
    excluded_orgs: list[str] = ["coderabbitai"]  # hard-excluded, always
    discovery_enabled: bool = True         # GitHub-wide hunt for bot-reviewed PRs on crawl
    discovery_per_use_case: int = 5        # search results ingested per use-case signature

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
