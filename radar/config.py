from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RADAR_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///data/workbench.sqlite3"
    source_db: Path = ROOT / "channelradar.sqlite3"
    evidence_dir: Path = ROOT / "evidence"
    admin_username: str = "admin"
    admin_password_hash: SecretStr
    session_secret: SecretStr = Field(min_length=32)
    cookie_secure: bool = True
    production: bool = False
    session_hours: int = Field(default=8, ge=1, le=24)
