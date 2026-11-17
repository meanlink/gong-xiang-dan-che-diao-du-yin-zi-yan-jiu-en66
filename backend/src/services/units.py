"""批次计量单位：每小时率与半小时人数之间的换算。

业务口径：
- ``count_per_half_hour``：每半小时的人数计数，是研究使用的默认口径。
- ``rate_per_hour``：供稿方按每小时报出的客流/借车率，换算为半小时人数需乘 0.5。
- 未声明单位的历史批次一律按半小时人数处理，不臆造单位。
"""
import math

COUNT_PER_HALF_HOUR = "count_per_half_hour"
RATE_PER_HOUR = "rate_per_hour"
DEFAULT_UNIT = COUNT_PER_HALF_HOUR
RESEARCH_UNIT = COUNT_PER_HALF_HOUR
COUNT_FIELDS = ("arrivals", "demand")

UNIT_LABELS = {
    COUNT_PER_HALF_HOUR: "人数 / 半小时",
    RATE_PER_HOUR: "人次 / 小时（每小时率）",
}
UNIT_FACTORS = {
    COUNT_PER_HALF_HOUR: 1.0,
    RATE_PER_HOUR: 0.5,
}
UNIT_OPTIONS = [
    {"value": COUNT_PER_HALF_HOUR, "label": "人数 / 半小时（计数，默认）"},
    {"value": RATE_PER_HOUR, "label": "人次 / 小时（每小时率）"},
]
_HALF_HOUR_ALIASES = {
    "count_per_half_hour", "counts_half_hour", "half_hour_count", "half-hourly",
    "人/半小时", "人次/半小时", "人数/半小时",
}
_HOURLY_ALIASES = {
    "rate_per_hour", "per_hour", "per hour", "hourly", "hourly_rate",
    "rate_per_60_minutes", "人/小时", "人次/小时", "人数/小时", "每小时", "小时率",
}


class UnknownUnit(ValueError):
    """单位不在可受理范围内。"""


class ConversionError(ValueError):
    """原值无法换算为人数。"""


def canonical_unit(value):
    """返回规范单位；``None``/空串表示未声明。未知单位一律拒绝。"""
    if value is None:
        return None
    if not isinstance(value, str):
        raise UnknownUnit("单位须为文本")
    text = value.strip()
    if not text:
        return None
    key = ' '.join(text.lower().replace('-', '_').split())
    if key in _HALF_HOUR_ALIASES:
        return COUNT_PER_HALF_HOUR
    if key in _HOURLY_ALIASES:
        return RATE_PER_HOUR
    raise UnknownUnit(f"未知单位“{text}”，仅支持人数/半小时与人次/小时")


def effective_unit(value):
    return canonical_unit(value) or DEFAULT_UNIT


def factor_for(value):
    return UNIT_FACTORS[effective_unit(value)]


def label_for(value):
    return UNIT_LABELS[effective_unit(value)]


def safe_label(value):
    """展示用标签；历史脏数据里的未知单位原样展示，不使接口失败。"""
    try:
        return label_for(value)
    except UnknownUnit:
        return str(value)


def safe_effective(value):
    try:
        return effective_unit(value)
    except UnknownUnit:
        return str(value or '')


def safe_factor(value):
    try:
        return factor_for(value)
    except UnknownUnit:
        return 0.0


def _number(value, label):
    if isinstance(value, bool):
        raise ConversionError(f"{label}不是有效计数")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ConversionError(f"{label}不是有效计数")
    if not math.isfinite(number) or number < 0:
        raise ConversionError(f"{label}须为非负有限数值")
    return number


def normalize(records, unit):
    """把原值换算成研究口径的人数。

    换算永远以原值为起点，因此重试不会把已换算值再乘一次。
    ``records`` 不会被修改。返回换算结果、样例与前后合计。
    """
    factor = factor_for(unit)
    converted, samples = [], []
    before = {key: 0.0 for key in COUNT_FIELDS}
    after = {key: 0.0 for key in COUNT_FIELDS}
    for index, row in enumerate(records, 1):
        if not isinstance(row, dict):
            raise ConversionError(f"第 {index} 行不是有效观测")
        item = dict(row)
        sample = {"station": row.get("station"), "period": row.get("period"), "before": {}, "after": {}}
        for key, label in (("arrivals", "附近到达客流"), ("demand", "借车需求")):
            value = _number(row.get(key), f"第 {index} 行{label}")
            before[key] += value
            item[key] = value * factor
            after[key] += item[key]
            sample["before"][key] = row.get(key)
            sample["after"][key] = item[key]
        converted.append(item)
        if index <= 3:
            samples.append(sample)
    return {
        "records": converted,
        "unit_from": unit or "",
        "unit_to": RESEARCH_UNIT,
        "factor": factor,
        "before_totals": before,
        "after_totals": after,
        "samples": samples,
    }


def convert_records(records, unit):
    return normalize(records, unit)["records"]


def records_report(records, unit):
    result = normalize(records, unit)
    result.pop("records")
    return result
