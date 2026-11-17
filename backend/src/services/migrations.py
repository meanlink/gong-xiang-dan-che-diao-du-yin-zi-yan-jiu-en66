"""逐批在线单位迁移。

设计要点：
- 迁移只写 ``Dataset.research_records``，``Dataset.records`` 的原值永不覆盖。
- 每批一个 ``MigrationItem``；已完成批次在恢复、暂停继续、重试时都跳过。
- 换算始终从原值重新计算，重试不会把已换算值再乘一次。
- 每轮迁移有单调版本号；新轮开始即接管旧轮，旧轮在写回前复核版本，
  失去资格后只标记 ``abandoned``，不再写批次。
"""
import time

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from src.config.database import Session
from src.models import Dataset, MigrationItem, MigrationRun
from src.services import units
from src.services.audit import record

ACTIVE_STATUSES = ('pending', 'running', 'paused')
BATCH_LIMIT = 5
QUIET_SECONDS = 1.5


def latest(db):
    return db.scalar(select(MigrationRun).order_by(MigrationRun.version.desc()).limit(1))


def active(db):
    run = latest(db)
    if run and run.status in ACTIVE_STATUSES:
        return run
    return None


def start(db, actor):
    """开始一轮迁移；若已有活动轮次，则接管并使其失去写回资格。"""
    for _ in range(5):
        current = latest(db)
        version = (current.version if current else 0) + 1
        now = time.time()
        if current and current.status in ACTIVE_STATUSES:
            db.execute(
                update(MigrationRun)
                .where(MigrationRun.id == current.id, MigrationRun.status.in_(ACTIVE_STATUSES))
                .values(status='superseded', paused=True, finished_at=now,
                        note=f'被第 {version} 轮迁移接管，停止写回')
            )
            # 旧轮的待办项一并作废，避免旧轮恢复后继续写。
            db.execute(
                update(MigrationItem)
                .where(MigrationItem.run_id == current.id,
                       MigrationItem.status.in_(('pending', 'processing')))
                .values(status='abandoned', reason=f'第 {version} 轮接管',
                        finished_at=now)
            )
        run = MigrationRun(version=version, status='running', paused=False, started_by=actor,
                           created_at=now, heartbeat_at=now, note='等待逐批迁移')
        db.add(run)
        try:
            db.flush()
        except IntegrityError:
            # 两个并发启动争用同一个版本号；回滚后重新读取并接管。
            db.rollback()
            continue
        return run
    raise RuntimeError('迁移轮次创建冲突，请重试')


def pause(db):
    run = latest(db)
    if not run or run.status not in ('pending', 'running'):
        raise ValueError('当前没有可暂停的迁移')
    run.paused = True
    run.status = 'paused'
    run.note = '已暂停；已完成批次不会重做'
    return run


def resume(db):
    run = latest(db)
    if not run or run.status != 'paused':
        raise ValueError('当前没有已暂停的迁移')
    run.paused = False
    run.status = 'running'
    run.note = '继续迁移，跳过已完成批次'
    run.heartbeat_at = time.time()
    return run


def retry_failed(db):
    run = latest(db)
    if not run or run.status not in ('running', 'paused', 'completed'):
        raise ValueError('当前没有可重试的迁移')
    failed = list(db.scalars(select(MigrationItem).where(
        MigrationItem.run_id == run.id, MigrationItem.status == 'failed')))
    if not failed:
        raise ValueError('没有失败批次需要重试')
    for item in failed:
        item.status = 'pending'
        item.reason = ''
        item.finished_at = None
    run.status = 'running'
    run.paused = False
    run.finished_at = None
    run.report = {}
    run.heartbeat_at = time.time()
    run.note = f'重试 {len(failed)} 个失败批次，按原值重新换算'
    return run


def recover(db):
    """worker 重启后把中断的批次放回待迁移，不重复已完成批次。"""
    run = latest(db)
    if not run or run.status not in ACTIVE_STATUSES:
        return
    db.execute(
        update(MigrationItem)
        .where(MigrationItem.run_id == run.id, MigrationItem.status == 'processing')
        .values(status='pending', started_at=None)
    )
    if run.status == 'pending':
        run.status = 'running'
    if not run.paused:
        run.note = '中断恢复：跳过已完成批次，继续待迁批次'


def _supersede(db, run, note):
    run.status = 'superseded'
    run.paused = True
    run.finished_at = time.time()
    run.note = note
    db.execute(
        update(MigrationItem)
        .where(MigrationItem.run_id == run.id,
               MigrationItem.status.in_(('processing', 'pending')))
        .values(status='abandoned', reason=note, finished_at=time.time())
    )


def _next_item(db, run):
    """优先重试 pending 项，再领取本轮到目前尚未登记的批次。"""
    item = db.scalar(
        select(MigrationItem)
        .where(MigrationItem.run_id == run.id, MigrationItem.status == 'pending')
        .order_by(MigrationItem.dataset_id)
        .limit(1)
    )
    if item:
        dataset = db.get(Dataset, item.dataset_id)
        if dataset is None:
            item.status = 'failed'
            item.reason = '批次已不存在'
            item.finished_at = time.time()
            return None, item, False
        item.status = 'processing'
        item.attempts = (item.attempts or 0) + 1
        item.started_at = time.time()
        item.reason = ''
        return dataset, item, False
    dataset = db.scalar(
        select(Dataset)
        .where(~Dataset.id.in_(select(MigrationItem.dataset_id).where(MigrationItem.run_id == run.id)))
        .order_by(Dataset.id)
        .limit(1)
    )
    if not dataset:
        return None, None, False
    item = MigrationItem(
        run_id=run.id, dataset_id=dataset.id, dataset_name=dataset.name, status='processing',
        unit_from=dataset.unit or '', unit_to=units.RESEARCH_UNIT,
        records=len(dataset.records or []), attempts=1, started_at=time.time(),
        arrived_during_migration=bool(dataset.created_at > run.created_at),
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None, None, True
    return dataset, item, False


def _claim(db, run, item):
    """写回前复核轮次资格：锁住轮次行，确认自己仍是最新且未暂停/接管。"""
    locked = db.execute(
        select(MigrationRun).where(MigrationRun.id == run.id).with_for_update()
    ).scalar_one_or_none()
    newest = db.scalar(select(func.max(MigrationRun.version)))
    if locked is None or locked.status != 'running' or locked.version != run.version or newest != run.version:
        item.status = 'abandoned'
        item.reason = '迁移轮次已被接管，放弃写回'
        item.finished_at = time.time()
        return False, 'superseded'
    if locked.paused:
        # 暂停不是失败：批次退回待迁，继续时按原值重新换算。
        item.status = 'pending'
        item.reason = '迁移已暂停，本批未写回'
        item.started_at = None
        return False, 'paused'
    return True, 'ok'


def _convert(db, run, dataset, item):
    """从原值换算并写回；写回前复核轮次资格。"""
    item.unit_from = dataset.unit or ''
    item.unit_to = units.RESEARCH_UNIT
    item.records = len(dataset.records or [])
    claimed, state = _claim(db, run, item)
    if not claimed:
        return 'stop'

    try:
        result = units.normalize(dataset.records or [], dataset.unit or '')
    except Exception as error:
        # 本批确实无法从原值换算；记失败原因，不阻断其余批次。
        item.status = 'failed'
        item.reason = str(error)[:490] or '无法换算为人数'
        item.finished_at = time.time()
        dataset.migration_status = 'failed'
        run.heartbeat_at = time.time()
        return 'done'

    dataset.research_records = result['records']
    dataset.migration_status = 'converted'
    item.status = 'converted'
    item.before_totals = result['before_totals']
    item.after_totals = result['after_totals']
    item.samples = result['samples']
    item.reason = ''
    item.finished_at = time.time()
    run.heartbeat_at = time.time()
    return 'done'


def process(db, run, limit=BATCH_LIMIT):
    done = 0
    while done < limit:
        db.refresh(run)
        if run.status not in ('pending', 'running') or run.paused:
            break
        newest = db.scalar(select(func.max(MigrationRun.version)))
        if newest != run.version:
            _supersede(db, run, '检测到更新轮次，停止写回')
            db.commit()
            break
        dataset, item, retry = _next_item(db, run)
        if retry:
            run = db.get(MigrationRun, run.id)
            continue
        if item is not None and dataset is None:
            db.commit()
            done += 1
            continue
        if dataset is None:
            break
        outcome = _convert(db, run, dataset, item)
        db.commit()
        done += 1
        if outcome == 'stop':
            break
    return done


def _counts(db, run):
    """统计真实批次的待迁数量，避免已删除批次把进度算成负数。"""
    registered = select(MigrationItem.dataset_id).where(MigrationItem.run_id == run.id)
    unregistered = db.scalar(
        select(func.count()).select_from(Dataset).where(~Dataset.id.in_(registered))) or 0
    items = list(db.scalars(select(MigrationItem).where(MigrationItem.run_id == run.id)))
    unfinished = sum(1 for item in items if item.status in ('pending', 'processing'))
    return unregistered + unfinished, items


def _audit(db, run):
    """核对全部批次；未完待迁时不报完成，缺项在完成报告里列出原因。"""
    total = db.scalar(select(func.count()).select_from(Dataset)) or 0
    pending, items = _counts(db, run)
    if pending:
        run.note = f'待迁移 {pending} 批；接报与分析不受影响'
        return False
    if time.time() - run.heartbeat_at < QUIET_SECONDS:
        return False
    missing = [item for item in items if item.status != 'converted']
    arrived = sum(1 for item in items if item.arrived_during_migration)
    finished_at = time.time()
    run.report = {
        'total': total,
        'historical': total - arrived,
        'arrived': arrived,
        'converted': len(items) - len(missing),
        'failed': len(missing),
        'ok': not missing,
        'missing': [{'dataset_id': item.dataset_id, 'dataset': item.dataset_name,
                     'status': item.status, 'reason': item.reason or '换算未完成'}
                    for item in missing],
        'finished_at': finished_at,
    }
    run.status = 'completed'
    run.finished_at = finished_at
    run.note = (f'已完成核对：历史 {total - arrived} 批、迁移期间新增 {arrived} 批'
                + (f'；{len(missing)} 批缺项见原因' if missing else '，全部换算完毕'))
    record(db, 'worker', 'dataset.migration.completed',
           {'run': run.id, 'version': run.version, 'total': total, 'arrived': arrived,
            'missing': len(missing)})
    return True


def tick():
    """worker 每次循环调用：推进当前轮次，全部核实后封存完成报告。"""
    with Session() as db:
        run = active(db)
        if not run or run.paused:
            return
        process(db, run)
        db.refresh(run)
        if run.status == 'running' and not run.paused:
            finished = _audit(db, run)
            db.commit()
            return finished


def run_dict(run):
    if not run:
        return None
    return {'id': run.id, 'version': run.version, 'status': run.status, 'paused': bool(run.paused),
            'started_by': run.started_by, 'created_at': run.created_at, 'finished_at': run.finished_at,
            'heartbeat_at': run.heartbeat_at, 'note': run.note, 'report': run.report or {}}


def item_dict(item):
    return {'id': item.id, 'run_id': item.run_id, 'dataset_id': item.dataset_id,
            'dataset': item.dataset_name, 'status': item.status, 'unit_from': item.unit_from, 'unit_from_label': units.safe_label(item.unit_from),
            'unit_to': item.unit_to, 'unit_to_label': units.safe_label(item.unit_to), 'records': item.records, 'before_totals': item.before_totals or {},
            'after_totals': item.after_totals or {}, 'samples': item.samples or [],
            'reason': item.reason, 'attempts': item.attempts,
            'arrived_during_migration': bool(item.arrived_during_migration),
            'started_at': item.started_at, 'finished_at': item.finished_at}


def snapshot(db):
    run = latest(db)
    total = db.scalar(select(func.count()).select_from(Dataset)) or 0
    if not run:
        # 尚未开始迁移：待迁 = 未换算或换算失败的批次；新接报批次已是研究口径。
        pending_filter = (Dataset.migration_status.is_(None)) | Dataset.migration_status.in_(('', 'legacy', 'failed'))
        pending = list(db.scalars(select(Dataset).where(pending_filter).order_by(Dataset.id).limit(100)))
        pending_total = db.scalar(select(func.count()).select_from(Dataset).where(pending_filter)) or 0
        return {'run': None,
                'counts': {'total': total, 'converted': total - pending_total, 'failed': 0,
                           'pending': pending_total, 'processing': 0,
                           'abandoned': 0, 'arrived': 0},
                'items': [],
                'pending_datasets': [{'id': d.id, 'name': d.name, 'rows': len(d.records or []),
                                      'unit': d.unit or '', 'unit_label': units.safe_label(d.unit or ''),
                                      'created_at': d.created_at} for d in pending],
                'missing': [], 'runs': []}
    items = list(db.scalars(select(MigrationItem).where(MigrationItem.run_id == run.id)
                            .order_by(MigrationItem.dataset_id)))
    processed = {item.dataset_id for item in items}
    pending_query = select(Dataset).order_by(Dataset.id).limit(100)
    if processed:
        pending_query = pending_query.where(~Dataset.id.in_(processed))
    pending_datasets = list(db.scalars(pending_query))
    pending_count, _ = _counts(db, run)
    missing = (run.report or {}).get('missing') or [
        {'dataset_id': item.dataset_id, 'dataset': item.dataset_name,
         'status': item.status, 'reason': item.reason or '换算未完成'}
        for item in items if item.status != 'converted']
    runs = list(db.scalars(select(MigrationRun).order_by(MigrationRun.version.desc()).limit(5)))
    return {
        'run': run_dict(run),
        'counts': {'total': total,
                   'converted': sum(1 for item in items if item.status == 'converted'),
                   'failed': sum(1 for item in items if item.status == 'failed'),
                   'pending': pending_count,
                   'processing': sum(1 for item in items if item.status == 'processing'),
                   'abandoned': sum(1 for item in items if item.status == 'abandoned'),
                   'arrived': sum(1 for item in items if item.arrived_during_migration)},
        'items': [item_dict(item) for item in items],
        'pending_datasets': [{'id': d.id, 'name': d.name, 'rows': len(d.records or []),
                              'unit': d.unit or '', 'unit_label': units.safe_label(d.unit or ''),
                              'created_at': d.created_at} for d in pending_datasets],
        'missing': missing or [],
        'runs': [run_dict(r) for r in runs],
    }
