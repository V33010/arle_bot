from pydantic import BaseModel, HttpUrl


class SkinChromas(BaseModel):
    uuid: str
    displayName: str
    displayIcon: None | str
    fullRender: None | str  # TODO : add some validation back later
    swatch: None | str
    streamedVideo: HttpUrl | None
    assetPath: str | None
    pickrate: int = 0
    total_occurance_rate: int = 0
