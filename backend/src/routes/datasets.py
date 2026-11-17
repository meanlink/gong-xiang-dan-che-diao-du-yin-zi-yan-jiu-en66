from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import Dataset
from src.schemas.dataset import DatasetInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import datasets, migrations
from src.services.audit import record
from src.services.dataset_view import describe, research_rows
from src.utils.serialization import dataset_dict

router = APIRouter(prefix='/datasets')


@router.get('')
def listing(db=Depends(get_db), u=Depends(current_user)):
    return [dataset_dict(d) for d in db.scalars(select(Dataset).order_by(Dataset.id.desc()))]


@router.post('', status_code=201)
def create(data: DatasetInput, db=Depends(get_db), u=Depends(can_write)):
    d = datasets.create(db, data)
    record(db, u.email, 'dataset.create', {'id': d.id, 'rows': len(d.records),
                                           'unit': d.unit or '', 'source': d.source})
    db.commit()
    return {**dataset_dict(d), **describe(d)}


# 迁移路由必须先于 /{id}，否则会被路径参数吞掉。
@router.get('/migration/status')
def migration_status(db=Depends(get_db), u=Depends(current_user)):
    return migrations.snapshot(db)


@router.post('/migration/start', status_code=201)
def migration_start(db=Depends(get_db), u=Depends(admin_only)):
    run = migrations.start(db, u.email)
    record(db, u.email, 'dataset.migration.start', {'run': run.id, 'version': run.version})
    db.commit()
    return migrations.snapshot(db)


@router.post('/migration/pause')
def migration_pause(db=Depends(get_db), u=Depends(admin_only)):
    try:
        run = migrations.pause(db)
    except ValueError as error:
        raise HTTPException(409, str(error))
    record(db, u.email, 'dataset.migration.pause', {'run': run.id, 'version': run.version})
    db.commit()
    return migrations.snapshot(db)


@router.post('/migration/resume')
def migration_resume(db=Depends(get_db), u=Depends(admin_only)):
    try:
        run = migrations.resume(db)
    except ValueError as error:
        raise HTTPException(409, str(error))
    record(db, u.email, 'dataset.migration.resume', {'run': run.id, 'version': run.version})
    db.commit()
    return migrations.snapshot(db)


@router.post('/migration/retry')
def migration_retry(db=Depends(get_db), u=Depends(admin_only)):
    try:
        run = migrations.retry_failed(db)
    except ValueError as error:
        raise HTTPException(409, str(error))
    record(db, u.email, 'dataset.migration.retry', {'run': run.id, 'version': run.version})
    db.commit()
    return migrations.snapshot(db)


@router.get('/{id}')
def detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    d = db.get(Dataset, id)
    if not d:
        raise HTTPException(404, '数据批次不存在')
    # 原值始终可核对；明细另附研究口径换算值。
    return {**dataset_dict(d), **describe(d), 'records': d.records,
            'research_records': research_rows(d, 30)}


@router.get('/{id}/migration')
def migration_detail(id: int, db=Depends(get_db), u=Depends(current_user)):
    d = db.get(Dataset, id)
    if not d:
        raise HTTPException(404, '数据批次不存在')
    return {**describe(d), 'records': d.records, 'research_records': research_rows(d, 30)}
