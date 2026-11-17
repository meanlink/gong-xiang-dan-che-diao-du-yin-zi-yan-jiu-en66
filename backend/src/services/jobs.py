import time
from fastapi import HTTPException
from redis import Redis

from src.config.settings import REDIS_URL
from src.models import Dataset, Job
from src.services import units
from src.services.business import metadata
from src.services.datasets import research_records, resolve_unit


def _unit_basis(dataset):
    """研究受理时的单位依据：声明单位、生效单位、换算系数、来源口径。"""
    declared = dataset.unit or ''
    effective = units.safe_effective(declared)
    return {
        'declared': declared,
        'effective': effective,
        'label': units.safe_label(declared),
        'factor': units.safe_factor(declared),
        'research_unit': units.RESEARCH_UNIT,
        'research_label': units.label_for(units.RESEARCH_UNIT),
        'source': 'batch_declared' if declared else 'legacy_undeclared_default_count',
        'batch_research_state': dataset.migration_status or 'unmigrated',
        'batch_records': len(dataset.records or []),
    }


def create(db, data, user):
    dataset = db.get(Dataset, data.dataset_id)
    if not dataset:
        raise HTTPException(404, '数据批次不存在')
    allowed = {p['key']: p for p in metadata().get('parameters', [])}
    if set(data.params) - set(allowed):
        raise HTTPException(422, '包含未知分析参数')
    params = {k: p['default'] for k, p in allowed.items()}
    params.update(data.params)
    for key, p in allowed.items():
        v = params[key]
        if p['type'] == 'number':
            try:
                v = float(v)
                if not (p.get('min', -1e9) <= v <= p.get('max', 1e9)):
                    raise ValueError()
                params[key] = v
            except (ValueError, TypeError):
                raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options', [])]:
            raise HTTPException(422, f'{p["label"]} 不是有效选项')

    # 受理即封定整份样本与单位依据；等待计算期间不再读取批次现状。
    try:
        sample = list(research_records(dataset))
    except HTTPException:
        raise
    basis = _unit_basis(dataset)
    basis['sample_rows'] = len(sample)
    basis['sealed_at'] = time.time()
    j = Job(name=data.name, dataset_id=data.dataset_id, params=params, created_by=user.id,
            created_at=time.time(), status='queued', sample_records=sample, unit_basis=basis)
    db.add(j); db.flush()
    return j


def enqueue(job_id):
    try:
        r = Redis.from_url(REDIS_URL); r.rpush('analysis:queue', job_id); r.close()
    except Exception:
        pass  # SQL queued status is the durable fallback
