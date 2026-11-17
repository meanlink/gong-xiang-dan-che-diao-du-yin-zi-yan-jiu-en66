from fastapi import HTTPException
from sqlalchemy import select

from src.models import Dataset
from src.services import units
from src.services.business import metadata
from src.utils.serialization import checksum
import math, time


def resolve_unit(value):
    """接收批次单位；未声明沿用人数，未知单位拒收。"""
    try:
        return units.canonical_unit(value) or ''
    except units.UnknownUnit as error:
        raise HTTPException(422, str(error))


def research_records(dataset):
    """研究口径记录：优先用迁移写出的换算结果，否则从原值即时换算。"""
    if dataset.research_records:
        return dataset.research_records
    try:
        return units.convert_records(dataset.records or [], dataset.unit or '')
    except (units.ConversionError, units.UnknownUnit) as error:
        raise HTTPException(422, f'批次原值无法换算为人数：{error}')


def create(db, data):
    name = data.name.strip()
    if len(name) < 2:
        raise HTTPException(422, '批次名称去除空格后至少需要两个字符')
    if db.scalar(select(Dataset).where(Dataset.name == name)):
        raise HTTPException(409, '该数据批次名已存在，请修改名称')
    unit = resolve_unit(data.unit)
    for index, row in enumerate(data.records):
        if not isinstance(row, dict):
            raise HTTPException(422, f'第 {index + 1} 行不是有效观测')
        for c in metadata()['columns']:
            value = row.get(c['key'])
            if value is None or value == '':
                raise HTTPException(422, f'第 {index + 1} 行缺少字段 {c["label"]}')
            if c['type'] == 'number':
                try:
                    if isinstance(value, bool) or not math.isfinite(float(value)):
                        raise ValueError()
                    row[c['key']] = float(value)
                except (TypeError, ValueError, OverflowError):
                    raise HTTPException(422, f'第 {index + 1} 行 {c["label"]} 必须为有限数值')
        if float(row['arrivals']) < 0 or float(row['demand']) < 0:
            raise HTTPException(422, f'第 {index + 1} 行客流与借车量须为非负数')
    try:
        converted = units.convert_records(data.records, unit)
    except units.ConversionError as error:
        raise HTTPException(422, f'批次无法换算为研究人数：{error}')
    d = Dataset(name=name, source=data.source, records=data.records, checksum=checksum(data.records),
                unit=unit, research_records=converted, migration_status='accepted',
                created_at=time.time())
    db.add(d); db.flush()
    return d
