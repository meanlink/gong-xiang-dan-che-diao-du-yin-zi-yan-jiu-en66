from sqlalchemy import String, JSON, Double
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class Dataset(Base):
    __tablename__ = 'datasets'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    source: Mapped[str] = mapped_column(String(200), default='manual.json')
    # 供稿方原值，任何迁移都不覆盖这里的记录。
    records: Mapped[list] = mapped_column(JSON)
    checksum: Mapped[str] = mapped_column(String(64))
    # 批次声明的单位；空串表示旧数据未声明，按半小时人数处理。
    unit: Mapped[str] = mapped_column(String(40), default='')
    # 迁移写出的研究口径（人数 / 半小时）；未迁移时为空。
    research_records: Mapped[list] = mapped_column(JSON, default=list)
    migration_status: Mapped[str] = mapped_column(String(20), default='')
    created_at: Mapped[float] = mapped_column(Double)
