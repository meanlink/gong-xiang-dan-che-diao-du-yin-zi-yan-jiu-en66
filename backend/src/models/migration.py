from sqlalchemy import String, JSON, Double, Integer, Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base


class MigrationRun(Base):
    """逐批单位迁移的一轮执行。

    ``version`` 单调递增；并发启动时只有版本最高的一轮拥有写回资格，
    旧轮次随后进入 ``superseded``，不再写回批次。
    """

    __tablename__ = 'migration_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    status: Mapped[str] = mapped_column(String(20), default='pending')
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    started_by: Mapped[str] = mapped_column(String(150), default='')
    created_at: Mapped[float] = mapped_column(Double)
    heartbeat_at: Mapped[float] = mapped_column(Double, default=0.0)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    cursor: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(String(500), default='')


class MigrationItem(Base):
    """单批次的迁移记录；``status`` 是恢复与重试的幂等锚点。"""

    __tablename__ = 'migration_items'
    __table_args__ = (UniqueConstraint('run_id', 'dataset_id', name='uq_migration_item_dataset'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    dataset_id: Mapped[int] = mapped_column(Integer, index=True)
    dataset_name: Mapped[str] = mapped_column(String(160), default='')
    status: Mapped[str] = mapped_column(String(20), default='pending')
    unit_from: Mapped[str] = mapped_column(String(40), default='')
    unit_to: Mapped[str] = mapped_column(String(40), default='')
    records: Mapped[int] = mapped_column(Integer, default=0)
    before_totals: Mapped[dict] = mapped_column(JSON, default=dict)
    after_totals: Mapped[dict] = mapped_column(JSON, default=dict)
    samples: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(String(500), default='')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    arrived_during_migration: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
