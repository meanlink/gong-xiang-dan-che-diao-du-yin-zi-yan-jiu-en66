import hashlib, json

from src.services import units


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def dataset_dict(d):
    return {'id': d.id, 'name': d.name, 'source': d.source, 'rows': len(d.records),
            'checksum': d.checksum, 'created_at': d.created_at,
            'unit': d.unit or '', 'unit_label': units.safe_label(d.unit or ''),
            'migration_status': d.migration_status or ''}


def job_dict(j):
    return {k: getattr(j, k) for k in ['id', 'name', 'dataset_id', 'params', 'status', 'result',
                                       'error', 'approved', 'unit_basis', 'created_at', 'finished_at']}


def report_dict(r):
    return {k: getattr(r, k) for k in ['id', 'name', 'job_id', 'destination', 'interval_seconds', 'next_run', 'enabled']}


def delivery_dict(d):
    return {k: getattr(d, k) for k in ['id', 'report_id', 'created_at', 'checksum', 'filename', 'destination']}
