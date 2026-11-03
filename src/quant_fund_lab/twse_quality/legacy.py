"""Conservative translation of legacy issues; unknown messages remain blocking."""
from __future__ import annotations

from dataclasses import replace

from .types import FindingCode, ReadinessFinding

EXACT_CODES = {
    "缺少該月官方價量檔": FindingCode.MISSING_MONTH,
    "缺少政策允許的該月價量檔": FindingCode.MISSING_MONTH,
    "價格來源衝突；需核對原始來源": FindingCode.SOURCE_CONFLICT,
    "供應商記錄無報價；不能當作停牌或可交易價格": FindingCode.MISSING_SESSION,
    "缺少價格；請補官方資料或有來源的停牌紀錄": FindingCode.MISSING_SESSION,
    "減資或官方參考價顯示可能含現金增資等未建模權利，不能僅按配股/股利計算": FindingCode.UNSUPPORTED_EVENT,
    "配股/股利與官方除權息資料不一致": FindingCode.EVENT_CONFLICT,
    "企業行動日缺少可核對的價量；無法安全估值": FindingCode.EVENT_CONFLICT,
    "官方企業行動索引或恢復交易註記有事件，actions.csv 缺少有來源的配股率/股利": FindingCode.EVENT_CONFLICT,
    "交易日曆缺少整日資料；請核對休市公告": FindingCode.CALENDAR,
    "休市紀錄與官方成交價量衝突": FindingCode.CALENDAR,
    "週末交易日尚未支援，請核對官方交易日曆": FindingCode.CALENDAR,
    "停牌紀錄與官方成交價量衝突": FindingCode.EVENT_CONFLICT,
}


def legacy_findings(issues: tuple, source_refs: tuple[str, ...], *,
                    policy_id: str = "twse_official") -> tuple[ReadinessFinding, ...]:
    """Retain original detail; merge only identical legacy records, never unknown ones."""
    findings = {}
    for issue in issues:
        detail = issue.detail
        code = EXACT_CODES.get(detail, FindingCode.UNKNOWN)
        discriminator = detail
        if detail.startswith("缺少企業行動覆蓋審核："):
            code = FindingCode.COVERAGE_REVIEW
            discriminator = detail.split("：", 1)[1]
        elif detail.startswith("缺少該年度官方") and detail.endswith("索引"):
            code = FindingCode.CALENDAR if "開休市" in detail else FindingCode.COVERAGE_REVIEW
        finding = ReadinessFinding(code, issue.symbol, issue.start, issue.end, detail,
                                   discriminator, source_refs, policy_id=policy_id)
        previous = findings.get(finding.finding_id)
        findings[finding.finding_id] = (replace(finding, occurrences=previous.occurrences + 1)
                                        if previous else finding)
    months = [f for f in findings.values() if f.code == FindingCode.MISSING_MONTH]
    for key, finding in list(findings.items()):
        if finding.code == FindingCode.MISSING_SESSION:
            dependencies = tuple(sorted(m.finding_id for m in months
                                        if m.symbol == finding.symbol
                                        and m.start <= finding.start <= m.end))
            findings[key] = replace(finding, depends_on=dependencies)
    return tuple(findings[key] for key in sorted(findings))
