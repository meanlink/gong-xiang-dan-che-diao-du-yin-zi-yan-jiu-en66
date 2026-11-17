from sqlalchemy import inspect, select, text

from src.config.database import Base, engine, Session
from src import models


# 旧库在线补齐的列：名称 -> 建列语句（SQLite 与 PostgreSQL 均可执行）。
_COLUMNS = {
    'datasets': {
        'unit': "VARCHAR(40) NOT NULL DEFAULT ''",
        'research_records': 'JSON',
        'migration_status': "VARCHAR(20) NOT NULL DEFAULT ''",
    },
    'jobs': {
        'sample_records': 'JSON',
        'unit_basis': 'JSON',
    },
}


def _add_columns():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    json_type = 'JSON' if engine.dialect.name == 'postgresql' else 'TEXT'
    with engine.begin() as conn:
        for table, columns in _COLUMNS.items():
            if table not in tables:
                continue
            existing = {column['name'] for column in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name in existing:
                    continue
                # ALTER 只加列，不重建表，迁移期间旧数据保持可读可接报。
                conn.execute(text(
                    f'ALTER TABLE {table} ADD COLUMN {name} {ddl.replace("JSON", json_type)}'))
        if 'datasets' in tables:
            # 旧数据未声明单位：保留原值，按半小时人数处理，等待逐批迁移。
            conn.execute(text("UPDATE datasets SET unit='' WHERE unit IS NULL"))
            conn.execute(text(
                "UPDATE datasets SET migration_status='legacy' "
                "WHERE migration_status IS NULL OR migration_status=''"))


def _backfill_jobs():
    """为特性上线前创建的分析任务补齐封存样本与单位依据。

    历史任务只能用当时的批次内容封样；无法换算时退回原值，避免升级阻塞启动。
    """
    from src.services import units

    with Session() as db:
        jobs = list(db.scalars(select(models.Job).where(
            (models.Job.sample_records.is_(None)) | (models.Job.sample_records == []))))
        for job in jobs:
            dataset = db.get(models.Dataset, job.dataset_id)
            if dataset is None:
                continue
            unit = dataset.unit or ''
            records = list(dataset.research_records or [])
            if not records:
                try:
                    records = units.convert_records(dataset.records or [], unit)
                except (units.ConversionError, units.UnknownUnit):
                    records = list(dataset.records or [])
            job.sample_records = records
            job.unit_basis = {
                'declared': unit,
                'effective': units.safe_effective(unit),
                'label': units.safe_label(unit),
                'factor': units.safe_factor(unit),
                'research_unit': units.RESEARCH_UNIT,
                'research_label': units.label_for(units.RESEARCH_UNIT),
                'source': 'batch_declared' if unit else 'legacy_undeclared_default_count',
                'batch_research_state': dataset.migration_status or 'legacy',
                'batch_records': len(dataset.records or []),
                'sample_rows': len(records),
                'backfilled': True,
            }
        db.commit()


def migrate():
    Base.metadata.create_all(engine)
    _add_columns()
    _backfill_jobs()


if __name__ == '__main__':
    migrate()
