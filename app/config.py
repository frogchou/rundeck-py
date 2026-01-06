import os
from functools import lru_cache
from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    host: str = Field("0.0.0.0", env="HOST")
    port: int = Field(8000, env="PORT")
    default_script: str = Field("/home/fix/dev.sh", env="DEFAULT_SCRIPT")
    allowed_script_root: str = Field("/home/fix", env="ALLOWED_SCRIPT_ROOT")
    allow_arbitrary_command: bool = Field(False, env="ALLOW_ARBITRARY_COMMAND")
    access_password: str = Field("frogchou", env="ACCESS_PASSWORD")


    # Comma-separated whitelist entries
    command_whitelist: str = Field(
        "echo,ls,cat,tail,grep,systemctl status,journalctl -u", env="COMMAND_WHITELIST"
    )

    class Config:
        env_file = ".env"
        case_sensitive = False

    @property
    def whitelist_commands(self) -> list[str]:
        return [item.strip() for item in self.command_whitelist.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=os.getenv("ENV_FILE", ".env"))
