from pydantic import HttpUrl, field_validator, ValidationInfo, ConfigDict
from pydantic import BaseModel as bmod
from typing import Literal


class CustomBaseModel(bmod):
    model_config = ConfigDict(extra="forbid")


class arleConfig(CustomBaseModel):
    version: str
    log_level: Literal["info", "debug", "error", "warn", "fatal"]
    log_file: str
    local_first: bool
    dev_mode: bool


class arleSecrets(CustomBaseModel):
    discord_token: str
    genius_token: str | None
    logfire_token: str | None


class devDb(CustomBaseModel):
    name: str
    database_url: HttpUrl | None | str
    database_auth_token: str | None


class prodDb(CustomBaseModel):
    name: str
    database_url: str | None
    database_auth_token: str | None

    @field_validator("database_url")
    def val_db_url(cls, v: str | None, info: ValidationInfo):
        dev_mode = info.context.get("dev_mode", False)
        if not dev_mode and not v:
            raise ValueError(
                "Need production database url when bot is not running in dev mode"
            )
        return v

    @field_validator("database_auth_token")
    def val_db_auth_token(cls, v: str | None, info: ValidationInfo):
        dev_mode = info.context.get("dev_mode", False)
        if not dev_mode and not v:
            raise ValueError(
                "Need production database auth token when bot is not running in dev mode"
            )
        return v


class databaseSecrets(CustomBaseModel):
    dev: devDb
    prod: prodDb


class ConfigValidator(CustomBaseModel):
    title: str
    arle: arleConfig
    secrets: arleSecrets
    database: databaseSecrets

    # Inject context for validators in nested models
    @classmethod
    def model_validate(cls, data):
        dev_mode = data["arle"]["dev_mode"]
        return super().model_validate(data, context={"dev_mode": dev_mode})
