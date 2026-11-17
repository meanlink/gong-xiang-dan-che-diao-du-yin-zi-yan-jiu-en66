from pydantic import BaseModel, Field


class DatasetInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source: str = Field(default='manual.json', max_length=200)
    records: list[dict] = Field(min_length=5, max_length=5000)
    # 未提供或空串表示沿用旧口径（人数/半小时）；未知单位在服务层拒收。
    unit: str | None = Field(default=None, max_length=40)
