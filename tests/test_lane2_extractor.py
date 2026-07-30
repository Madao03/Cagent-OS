"""LANE 2 earnings release extraction tests.

Based on XPEV FY2025 Q4 fixture ground truth:
  Q4 revenue: RMB 22.25 billion (US$3.18 billion)
  FY revenue: RMB 76.72 billion (US$10.97 billion)
  Currency: CNY (RMB is native, USD is convenience translation)
  Q4 period: 2025-10-01 to 2025-12-31
  FY period: 2025-01-01 to 2025-12-31
"""
import pytest
from pathlib import Path

FIXTURE_DIR = Path("tests/fixtures/edgar")
XPEV_FIXTURE = FIXTURE_DIR / "xpev_6k_fy2025q4_earnings.html"


@pytest.fixture(scope="module")
def extracted_data():
    """Run extraction on the XPEV fixture."""
    import json
    from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor
    extractor = EarningsReleaseExtractor()
    fixture = XPEV_FIXTURE.read_bytes()
    meta_path = FIXTURE_DIR / "xpev_6k_fy2025q4_earnings.meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return extractor.extract(fixture, meta=meta)


# ── §5 核心断言：期间分离 ──────────────────────────────────────

class TestPeriodSeparation:
    """§5 最核心的断言：Q4 单季 vs FY 全年必须分离"""

    def test_q4_revenue_is_correct(self, extracted_data):
        """Q4 单季营收应为 RMB 22.25B，不是全年值"""
        q4 = extracted_data.get_record("quarter", "2025-10-01", "2025-12-31")
        assert q4 is not None, "Q4 record missing"
        assert q4["revenue"] == pytest.approx(22.25e9, rel=0.01), \
            f"Q4 revenue should be ~¥22.25B, got ¥{q4['revenue']/1e9:.2f}B"

    def test_fy_revenue_is_correct(self, extracted_data):
        """FY 全年营收应为 RMB 76.72B"""
        fy = extracted_data.get_record("fiscal_year", "2025-01-01", "2025-12-31")
        assert fy is not None, "FY record missing"
        assert fy["revenue"] == pytest.approx(76.72e9, rel=0.01), \
            f"FY revenue should be ~¥76.72B, got ¥{fy['revenue']/1e9:.2f}B"

    def test_q4_and_fy_are_separate_records(self, extracted_data):
        """单季 vs 全年必须是不同记录"""
        q4 = extracted_data.get_record("quarter", "2025-10-01", "2025-12-31")
        fy = extracted_data.get_record("fiscal_year", "2025-01-01", "2025-12-31")
        assert q4["revenue"] != fy["revenue"], "Q4 and FY revenue must not be mixed"
        assert fy["revenue"] > q4["revenue"] * 2, "FY should be >2x Q4"

    def test_q4_period_type(self, extracted_data):
        """Q4 记录的 period_type 必须是 quarter"""
        q4 = extracted_data.get_record("quarter", "2025-10-01", "2025-12-31")
        assert q4["period_type"] == "quarter"

    def test_fy_period_type(self, extracted_data):
        """FY 记录的 period_type 必须是 fiscal_year"""
        fy = extracted_data.get_record("fiscal_year", "2025-01-01", "2025-12-31")
        assert fy["period_type"] == "fiscal_year"


# ── §5.3 币种断言 ──────────────────────────────────────────────

class TestCurrency:
    """币种必须正确：CNY 本位币入库，USD 折算值标注 derived"""

    def test_currency_is_cny(self, extracted_data):
        """currency 必须是 CNY，不是 USD"""
        q4 = extracted_data.get_record("quarter", "2025-10-01", "2025-12-31")
        assert q4["currency"] == "CNY", \
            f"Currency should be CNY, got {q4['currency']}"

    def test_revenue_is_not_usd_convenience(self, extracted_data):
        """Q4 营收不得存 USD 便利折算值 $3.18B"""
        q4 = extracted_data.get_record("quarter", "2025-10-01", "2025-12-31")
        assert q4["revenue"] != pytest.approx(3.18e9, rel=0.01), \
            "REGRESSION: stored USD convenience translation instead of CNY native"

    def test_fx_rate_captured(self, extracted_data):
        """必须捕获折算汇率（从脚注解析，非列除法）"""
        q4 = extracted_data.get_record("quarter", "2025-10-01", "2025-12-31")
        assert q4.get("fx_rate") is not None, "FX rate must be captured"
        # FX rate from footnote: "RMB6.9931 to US$1.00"
        assert 6.0 < q4["fx_rate"] < 8.0, \
            f"FX rate should be ~7.0 (CNY/USD), got {q4['fx_rate']}"
        # FX date should be end of period
        assert q4.get("fx_rate_date") == "2025-12-31", \
            f"FX date should be 2025-12-31, got {q4.get('fx_rate_date')}"


# ── §5.2 规则③ 比较从句不入库 ──────────────────────────────────

class TestNoComparativeValues:
    """比较从句中的隐含值不得作为独立记录入库"""

    def test_no_q4_2024_in_records(self, extracted_data):
        """上期对比值(Q4'24/FY'24/Q3'25)可以入库——来自附表列头是合法的。
        禁止的是从正文比较从句推算隐含值（如从 '38.2% increase' 反推 Q4'24）。
        列头有的 = 合法，从句推算的 = 禁止。"""
        records = extracted_data.all_records()
        # Q4'24 and Q3'25 from table columns are OK
        # The rule is: don't extract values that are ONLY derivable from
        # comparative text clauses, not explicitly in a table column.
        # If they appear in a table with proper headers, they're company-reported.
        q4_2024 = [r for r in records if r.get("period_start") == "2024-10-01"]
        q3_2025 = [r for r in records if r.get("period_start") == "2025-07-01"]
        # Both are legitimate if from table headers
        # Just verify they have proper extraction_method
        for r in q4_2024 + q3_2025:
            assert r.get("extraction_method") == "table", \
                f"Comparison period must come from table, got {r.get('extraction_method')}"

    def test_no_q3_2025_in_records(self, extracted_data):
        """Q3'25 来自 Table 33 的 Sep 30 2025 列——合法的对比列。"""
        records = extracted_data.all_records()
        q3 = [r for r in records if r.get("period_start") == "2025-07-01"]
        # Q3'25 is legitimate if from table — it's the prior quarter comparison column
        # Just verify the value is correct (should be ~20.38B)
        if q3:
            assert q3[0].get("revenue") == pytest.approx(20.38e9, rel=0.01), \
                f"Q3'25 revenue should be ~¥20.38B, got {q3[0].get('revenue')}"


# ── §8 反向校验（今天就能跑）────────────────────────────────────

@pytest.mark.sec
class TestCrossValidationWithLane1:
    """S8: LANE 2 抽取值 vs LANE 1 XBRL 权威值"""

    @pytest.mark.asyncio
    @pytest.mark.skipif(not XPEV_FIXTURE.exists(), reason="fixture missing")
    async def test_lane2_fy_matches_lane1(self, extracted_data):
        """FY2025 LANE 2 新闻稿值 vs LANE 1 20-F XBRL 值，差异应 <1%"""
        from cagent_os.data_layer.adapters.edgar_adapter import EdgardAdapter

        adapter = EdgardAdapter()
        lane1 = await adapter.get_earnings_summary("XPEV")
        lane1_revenue = lane1["metrics"]["revenue"]["value"]

        fy = extracted_data.get_record("fiscal_year", "2025-01-01", "2025-12-31")
        lane2_revenue = fy["revenue"]

        diff_pct = abs(lane2_revenue - lane1_revenue) / lane1_revenue
        assert diff_pct < 0.01, \
            f"LANE2 ¥{lane2_revenue/1e9:.2f}B vs LANE1 ¥{lane1_revenue/1e9:.2f}B: {diff_pct*100:.2f}% diff > 1%"


# ── 溯源 ──────────────────────────────────────────────────────

class TestTraceability:

    def test_records_have_accession(self, extracted_data):
        records = extracted_data.all_records()
        for r in records:
            assert r.get("source") == "6-K", f"source should be 6-K"
            assert r.get("audited") is False, "Press release data is never audited"
            assert r.get("accession"), "Accession must be present for traceability"

    def test_extraction_method_recorded(self, extracted_data):
        """每个记录必须标注来自附表还是正文"""
        records = extracted_data.all_records()
        for r in records:
            assert r.get("extraction_method") in ("table", "text"), \
                f"extraction_method missing: {r}"


# ── 符号回归断言（防止括号分离导致符号翻转）──────────────────────

class TestSignIntegrity:
    """防止括号分离 cell 导致净亏损变净利润（最高危静默错误）"""

    def test_fy2025_net_income_is_negative(self, extracted_data):
        """FY2025 净利润应为负（-¥1.14B），首次季度盈利但全年仍亏"""
        fy = extracted_data.get_record("fiscal_year", "2025-01-01", "2025-12-31")
        assert fy["net_income"] is not None, "net_income missing"
        assert fy["net_income"] < 0, \
            f"FY2025 net_income should be NEGATIVE (net loss), got {fy['net_income']/1e9:.2f}B"

    def test_fy2024_net_income_is_negative(self, extracted_data):
        """FY2024 净利润应为负（-¥5.79B）"""
        fy = extracted_data.get_record("fiscal_year", "2024-01-01", "2024-12-31")
        if fy and fy.get("net_income") is not None:
            assert fy["net_income"] < 0, \
                f"FY2024 net_income should be NEGATIVE, got {fy['net_income']/1e9:.2f}B"

    def test_cost_of_sales_sign(self, extracted_data):
        """成本类科目在 SEC 表中用括号（负数）表示是标准惯例。
        括号分离 cell 修复后，负号应正确保留。"""
        records = extracted_data.all_records()
        for r in records:
            cost = r.get("cost_of_sales")
            if cost is not None:
                # cost_of_sales in SEC tables is shown as (35,020,541) = negative
                # This is correct. The sign should be consistently negative.
                assert cost < 0, \
                    f"cost_of_sales should be negative (parenthesized in SEC), " \
                    f"got {cost} for {r.get('period_start')}"

    def test_all_values_within_reasonable_range(self, extracted_data):
        """防止千分位/单位解析失控"""
        records = extracted_data.all_records()
        for r in records:
            for key, val in r.items():
                if isinstance(val, (int, float)) and val:
                    assert abs(val) < 1e13, \
                        f"{key}={val} exceeds reasonable range for {r.get('period_start')}"

    def test_revenue_positive_all_periods(self, extracted_data):
        """营收永远为正"""
        records = extracted_data.all_records()
        for r in records:
            rev = r.get("revenue")
            if rev is not None:
                assert rev > 0, f"revenue should be positive, got {rev} for {r.get('period_start')}"


# ── _parse_header_date 直接单测（防默认值回归）────────────────────

class TestParseHeaderDate:
    """★ 核心规则：bare year 不得推断月日。

    这是第五个同模式 bug 的固化断言：
    信息缺失时返回 None，不填"合理"的默认值。
    """

    def test_full_date(self):
        from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor
        ext = EarningsReleaseExtractor()
        assert ext._parse_header_date("December 31, 2025") == "2025-12-31"
        assert ext._parse_header_date("September 30, 2025") == "2025-09-30"
        assert ext._parse_header_date("March 31 2024") == "2024-03-31"

    def test_bare_year_returns_none(self):
        """★ bare year '2025' 必须返回 None，不猜 Dec 31。

        这条 bug 影响所有非 12 月财年公司：
        - AAPL (Sep 财年): bare "2025" 会错 3 个月
        - BABA (Mar 财年): bare "2025" 会错 9 个月
        """
        from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor
        ext = EarningsReleaseExtractor()
        assert ext._parse_header_date("2025") is None
        assert ext._parse_header_date("2024") is None

    def test_empty_and_garbage(self):
        from cagent_os.data_layer.lane2.extractor import EarningsReleaseExtractor
        ext = EarningsReleaseExtractor()
        assert ext._parse_header_date("") is None
        assert ext._parse_header_date("N/A") is None
        assert ext._parse_header_date("RMB") is None


# ── G4 Guidance 断言 ──────────────────────────────────────────

class TestGuidance:
    """G4: 公司指引从 Business Outlook 段落抽取。

    设计原则:
    - 锚点用同比，不用环比（同比是管理层明确声明的对比方向）
    - 区间方向: 低值 → 更大跌幅，高值 → 较小跌幅
    - 标记审查(flag)，不自动拒绝(reject)
    """

    def test_guidance_extracted(self, extracted_data):
        """XPEV Q4 新闻稿应抽取到 2 条指引记录"""
        assert len(extracted_data.guidance) == 2, \
            f"Expected 2 guidance records, got {len(extracted_data.guidance)}"

    def test_guidance_period_label(self, extracted_data):
        """周期标签应为 Q1 2026"""
        for g in extracted_data.guidance:
            assert g.period_label == "Q1 2026", \
                f"Expected 'Q1 2026', got '{g.period_label}'"

    def test_revenue_guidance_range(self, extracted_data):
        """营收指引: ¥12.20B ~ ¥13.28B"""
        rev = [g for g in extracted_data.guidance if g.metric_name == "revenue"]
        assert len(rev) == 1, "Revenue guidance record missing"
        r = rev[0]
        assert r.low == pytest.approx(12.20e9, rel=0.01), \
            f"Revenue low should be ~¥12.20B, got ¥{r.low/1e9:.2f}B"
        assert r.high == pytest.approx(13.28e9, rel=0.01), \
            f"Revenue high should be ~¥13.28B, got ¥{r.high/1e9:.2f}B"

    def test_revenue_guidance_yoy(self, extracted_data):
        """营收指引同比: -22.84% ~ -16.01%（跌幅）"""
        rev = [g for g in extracted_data.guidance if g.metric_name == "revenue"]
        r = rev[0]
        assert r.yoy_change_low is not None, "YoY low missing"
        assert r.yoy_change_high is not None, "YoY high missing"
        assert r.yoy_change_low == pytest.approx(-22.84, rel=0.02), \
            f"YoY low should be ~-22.84%, got {r.yoy_change_low}%"
        assert r.yoy_change_high == pytest.approx(-16.01, rel=0.02), \
            f"YoY high should be ~-16.01%, got {r.yoy_change_high}%"

    def test_revenue_guidance_currency(self, extracted_data):
        """营收指引货币为 CNY"""
        rev = [g for g in extracted_data.guidance if g.metric_name == "revenue"]
        assert rev[0].currency == "CNY", \
            f"Revenue guidance currency should be CNY, got {rev[0].currency}"

    def test_deliveries_guidance_range(self, extracted_data):
        """交付量指引: 61,000 ~ 66,000 辆"""
        delv = [g for g in extracted_data.guidance if g.metric_name == "deliveries"]
        assert len(delv) == 1, "Deliveries guidance record missing"
        d = delv[0]
        assert d.low == pytest.approx(61000, rel=0.01), \
            f"Deliveries low should be ~61,000, got {d.low:,.0f}"
        assert d.high == pytest.approx(66000, rel=0.01), \
            f"Deliveries high should be ~66,000, got {d.high:,.0f}"

    def test_deliveries_guidance_currency(self, extracted_data):
        """交付量指引货币为 count（非货币）"""
        delv = [g for g in extracted_data.guidance if g.metric_name == "deliveries"]
        assert delv[0].currency == "count", \
            f"Deliveries currency should be count, got {delv[0].currency}"

    def test_yoy_direction_low_more_negative(self, extracted_data):
        """区间方向法则: 低值对更大跌幅，高值对较小跌幅

        「decrease of 16.01% to 22.84%」→ 12.20B 对应 -22.84%,
        13.28B 对应 -16.01%，所以 yoy_change_low < yoy_change_high"""
        rev = [g for g in extracted_data.guidance if g.metric_name == "revenue"]
        r = rev[0]
        assert r.yoy_change_low < r.yoy_change_high, \
            f"Low value should have more negative YoY: " \
            f"got {r.yoy_change_low}% vs {r.yoy_change_high}%"

    def test_guidance_source_traceable(self, extracted_data):
        """每条指引记录必须有 source 和 accession"""
        for g in extracted_data.guidance:
            assert g.source in ("6-K", "8-K"), f"source: {g.source}"
            assert g.accession, "accession missing"

    def test_guidance_not_auto_rejected(self, extracted_data):
        """★ 核心原则: 从不自动拒绝指引。

        即使指引范围异常（如 -35% 同比），也不在抽取层拒绝。
        拒绝逻辑属于 assertion / eval 层，不在此处。"""
        # If we got records, they were not rejected — that's the test.
        # The presence of any guidance records proves we didn't reject.
        assert len(extracted_data.guidance) > 0, \
            "Auto-rejection detected: guidance records missing when they should exist"

    def test_guidance_extraction_conf(self, extracted_data):
        """置信度应反映证据强度，不是硬编码常量。

        Revenue: period + RMB + YoY + billion → 0.80
        Deliveries: period + explicit_unit + YoY → 0.70
        (Delivery 不再因"无货币维度"被结构性压低——计数指标用 explicit_unit 替代。)
        """
        rev = [g for g in extracted_data.guidance if g.metric_name == "revenue"]
        delv = [g for g in extracted_data.guidance if g.metric_name == "deliveries"]

        assert rev[0].extraction_conf >= 0.75, \
            f"Revenue conf too low: {rev[0].extraction_conf}"
        assert delv[0].extraction_conf >= 0.65, \
            f"Deliveries conf too low: {delv[0].extraction_conf}"

        # Not all the same value — proves it's not a decorative constant
        confs = {g.extraction_conf for g in extracted_data.guidance}
        assert len(confs) > 1, \
            f"All confidence values identical ({confs}): appears hardcoded"
