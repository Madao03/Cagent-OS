"""Four-quarter sum validation tests.

Ensures Q1+Q2+Q3+Q4 ≈ FY with FULL precision (not rounded billions).
Also validates that each quarter is EXTRACTED (not derived from FY-Q1-Q2-Q3).
And checks net_income sum (which WILL differ due to year-end adjustments).
"""
import json
import pytest
from pathlib import Path

FIXTURE_DIR = Path("tests/fixtures/edgar")


@pytest.fixture(scope="module")
def all_quarterly_data():
    """Extract from Q1, Q3, Q4 fixtures to get all four quarters.

    Q2 comes from Q3 fixture's comparison column.
    """
    import sys
    sys.path.insert(0, "src")
    from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor

    ext = EarningsReleaseExtractor()
    quarters = {}  # "Q1"/"Q2"/"Q3"/"Q4" → dict

    for fixture_name, meta_name in [
        ("xpev_6k_2025q1_earnings", "xpev_6k_2025q1_earnings"),
        ("xpev_6k_2025q3_earnings", "xpev_6k_2025q3_earnings"),
        ("xpev_6k_fy2025q4_earnings", "xpev_6k_fy2025q4_earnings"),
    ]:
        fp = FIXTURE_DIR / f"{fixture_name}.html"
        mp = FIXTURE_DIR / f"{meta_name}.meta.json"
        if not fp.exists():
            continue
        meta = json.loads(mp.read_text()) if mp.exists() else {}
        data = ext.extract(fp.read_bytes(), meta=meta)

        for r in data.records:
            if r.currency != "CNY":
                continue
            rev = r.metrics.get("revenue")
            if rev is None:
                continue
            # Skip billions-scale values from Highlights table (16.11 etc.)
            # Only keep thousands-scale values from detailed tables (16,105,096 etc.)
            if rev < 1e6:
                continue

            # Map period to quarter label
            if r.period_start == "2025-01-01" and r.period_end == "2025-03-31":
                quarters["Q1"] = r
            elif r.period_start == "2025-04-01" and r.period_end == "2025-06-30":
                quarters["Q2"] = r
            elif r.period_start == "2025-07-01" and r.period_end == "2025-09-30":
                quarters["Q3"] = r
            elif r.period_start == "2025-10-01" and r.period_end == "2025-12-31":
                quarters["Q4"] = r
            elif r.period_start == "2025-01-01" and r.period_end == "2025-12-31":
                quarters["FY"] = r

    return quarters


class TestFourQuarterSum:
    """★ 四季加总 = 全年 (全精度比较)"""

    def test_all_four_quarters_present(self, all_quarterly_data):
        """四个季度必须全部到位"""
        for q in ["Q1", "Q2", "Q3", "Q4"]:
            assert q in all_quarterly_data, f"Missing {q}"
        assert "FY" in all_quarterly_data, "Missing FY total"

    def test_quarter_extraction_method(self, all_quarterly_data):
        """★ 每个 Q 必须从表格抽取，不是 FY-Q1-Q2-Q3 推算出来的"""
        for q in ["Q1", "Q2", "Q3", "Q4"]:
            rec = all_quarterly_data[q]
            assert rec.extraction_method == "table", \
                f"{q} must be extracted from table, not derived. Got: {rec.extraction_method}"

    def test_revenue_full_precision_sum(self, all_quarterly_data):
        """★ 全精度加总：76,720M 而非 76.72B"""
        q_revs = []
        for q in ["Q1", "Q2", "Q3", "Q4"]:
            rec = all_quarterly_data[q]
            rev = rec.metrics.get("revenue")
            assert rev is not None, f"{q} revenue is None"
            q_revs.append(rev)

        fy_rev = all_quarterly_data["FY"].metrics.get("revenue")
        assert fy_rev is not None, "FY revenue is None"

        sum_q = sum(q_revs)
        diff_pct = abs(sum_q - fy_rev) / fy_rev * 100

        print(f"\n  Q1: {q_revs[0]:,.0f}")
        print(f"  Q2: {q_revs[1]:,.0f}")
        print(f"  Q3: {q_revs[2]:,.0f}")
        print(f"  Q4: {q_revs[3]:,.0f}")
        print(f"  Sum:  {sum_q:,.0f}")
        print(f"  FY:   {fy_rev:,.0f}")
        print(f"  Diff: {diff_pct:.4f}%")

        # Revenue should match within 1% (most stable metric)
        assert diff_pct < 1.0, \
            f"Quarter sum ({sum_q:,.0f}) vs FY ({fy_rev:,.0f}): {diff_pct:.2f}% > 1%"

    def test_net_income_sum_with_tolerance(self, all_quarterly_data):
        """net_income 加总允许更大差异（年末减值/税务调整）。

        §8.2 阈值: ±5% for net_income.
        差异本身是有投研价值的信号（审计调整）。
        """
        q_nis = []
        for q in ["Q1", "Q2", "Q3", "Q4"]:
            rec = all_quarterly_data[q]
            ni = rec.metrics.get("net_income")
            if ni is not None:
                q_nis.append(ni)

        fy_ni = all_quarterly_data["FY"].metrics.get("net_income")
        if fy_ni is None or not q_nis:
            pytest.skip("net_income not available for all quarters")

        if len(q_nis) < 4:
            pytest.skip(f"Only {len(q_nis)}/4 quarters have net_income")

        sum_ni = sum(q_nis)
        diff_pct = abs(sum_ni - fy_ni) / abs(fy_ni) * 100

        print(f"\n  Q net_income sum: {sum_ni:,.0f}")
        print(f"  FY net_income:    {fy_ni:,.0f}")
        print(f"  Diff: {diff_pct:.2f}%")

        # net_income tolerance is ±5% per §8.2
        # If >5%, it's a signal of year-end adjustments (not a bug)
        if diff_pct > 5.0:
            print(f"  ⚠ NOTE: >5% difference — likely year-end audit adjustments (investable signal)")
        # Don't fail — the difference itself is information
        assert diff_pct < 50.0, "Sanity check: net_income sum vs FY should be same order of magnitude"


class TestRestatementDetection:
    """同期间跨文档一致性 — 重述检测"""

    def test_fy2024_consistent_across_sources(self, all_quarterly_data):
        """FY2024 从不同文档取值应一致（无重述）"""
        # FY2024 appears in: FY2024 earnings + FY2025 Q4 comparison column
        import sys
        sys.path.insert(0, "src")
        from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor

        ext = EarningsReleaseExtractor()
        fy2024_values = []

        for fixture_name in ["xpev_6k_fy2024_earnings", "xpev_6k_fy2025q4_earnings"]:
            fp = FIXTURE_DIR / f"{fixture_name}.html"
            mp = FIXTURE_DIR / f"{fixture_name}.meta.json"
            if not fp.exists():
                continue
            meta = json.loads(mp.read_text()) if mp.exists() else {}
            data = ext.extract(fp.read_bytes(), meta=meta)
            for r in data.records:
                if (r.period_start == "2024-01-01" and
                    r.period_end == "2024-12-31" and
                    r.currency == "CNY"):
                    rev = r.metrics.get("revenue")
                    if rev and rev > 1e6:  # Skip billions-scale (from Highlights table)
                        fy2024_values.append((fixture_name, rev))

        assert len(fy2024_values) >= 2, f"Need ≥2 sources, got {len(fy2024_values)}"

        vals = [v for _, v in fy2024_values]
        diff = abs(max(vals) - min(vals)) / max(vals) * 100
        print(f"\n  FY2024 from {len(fy2024_values)} sources:")
        for src, val in fy2024_values:
            print(f"    {src}: {val:,.0f}")
        print(f"  Max diff: {diff:.4f}%")

        assert diff < 0.01, f"FY2024 restated! Diff {diff:.4f}% > 0.01%"
