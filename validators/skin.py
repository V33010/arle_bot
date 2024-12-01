from pydantic import BaseModel, HttpUrl


class SkinChromas(BaseModel):
    uuid: str
    displayName: str
    displayIcon: HttpUrl | None
    fullRender: HttpUrl | None
    swatch: HttpUrl | None
    streamedVideo: HttpUrl | None
    assetPath: str | None
    pickrate: int = 0
    total_occurance_rate: int = 0
