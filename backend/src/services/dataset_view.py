from src.services import units


def conversion(dataset):
    """批次换算核对：原值合计与换算后合计、样例对照。"""
    try:
        return units.records_report(dataset.records or [], dataset.unit or '')
    except (units.ConversionError, units.UnknownUnit):
        return {'unit_from': dataset.unit or '', 'unit_to': units.RESEARCH_UNIT,
                'factor': units.safe_factor(dataset.unit or ''), 'before_totals': {},
                'after_totals': {}, 'samples': []}


def describe(dataset):
    """批次摘要：保留原值指纹、声明单位与研究口径的换算依据。"""
    return {
        'unit': dataset.unit or '',
        'unit_label': units.safe_label(dataset.unit or ''),
        'unit_declared': bool(dataset.unit),
        'research_unit': units.RESEARCH_UNIT,
        'research_unit_label': units.label_for(units.RESEARCH_UNIT),
        'research_state': dataset.migration_status or 'unmigrated',
        'conversion': conversion(dataset),
    }


def research_rows(dataset, limit=None):
    """明细展示用：优先已迁移的研究口径，否则用原值即时换算。"""
    rows = list(dataset.research_records or [])
    if not rows:
        try:
            rows = units.convert_records(dataset.records or [], dataset.unit or '')
        except (units.ConversionError, units.UnknownUnit):
            rows = []
    return rows[:limit] if limit else rows
