"""EDGAR LANE 1 regression tests.

固化验证清单的关键断言，特别盯防已修过的三个 bug：
  - fy 期间误用（XPEV 返回 ¥30,676M = FY2023）
  - 标签断档（AAPL 返回 $215.6B = FY2016）
  - 币种误判（XPEV/BABA 返回 USD 便利折算值）

使用关系/范围断言而非硬编码值（财报会更新）。
"""
import sys
import pytest

sys.path.insert(0, "src")

from cagent_os.data_layer.adapters.edgar_adapter import EdgardAdapter, _TAG_ALIASES


@pytest.fixture(scope="module")
def adapter():
    return EdgardAdapter()


# ── 反例基线：专门盯已修 bug 是否复发 ──────────────────────────────

@pytest.mark.sec
class TestRegressionBaselines:
    """These assertions exist specifically to catch regression of known bugs."""

    @pytest.mark.asyncio
    async def test_xpev_not_fy2023_regression(self, adapter):
        """Bug: fy 误用导致 XPEV 返回 FY2023 的 ¥30,676M（应为 FY2025 的 ¥76,720M）"""
        summary = await adapter.get_earnings_summary("XPEV")
        rev = summary["metrics"]["revenue"]
        assert rev["value"] != 30_676_000_000, "REGRESSION: fy bug — got FY2023 value"
        assert rev["end_date"][:4] == "2025", f"Expected FY2025, got end={rev['end_date']}"
        assert rev["value"] > 70e9, f"Revenue too low: ¥{rev['value']/1e6:.0f}M — possible fy bug"

    @pytest.mark.asyncio
    async def test_aapl_not_fy2016_regression(self, adapter):
        """Bug: 标签断档导致 AAPL 返回 FY2016 的 $215.6B（应为 FY2025 的 $416.2B）"""
        summary = await adapter.get_earnings_summary("AAPL")
        rev = summary["metrics"]["revenue"]
        assert rev["value"] != 215_639_000_000, "REGRESSION: tag bug — got FY2016 value"
        assert rev["value"] > 350e9, f"Revenue too low: ${rev['value']/1e9:.1f}B — possible tag fallback failure"

    @pytest.mark.asyncio
    async def test_xpev_currency_not_usd_regression(self, adapter):
        """Bug: 币种误判导致 XPEV 返回 USD 便利折算值（应为 CNY 本位币）"""
        summary = await adapter.get_earnings_summary("XPEV")
        assert summary["currency"] == "CNY", f"REGRESSION: currency bug — got {summary['currency']}"


# ── 正向断言：用范围/关系而非硬编码 ──────────────────────────────

@pytest.mark.sec
class TestPositiveAssertions:

    @pytest.mark.asyncio
    async def test_xpev_period_correct(self, adapter):
        """验证 #10: XPEV 最新年度 end_date = 2025-12-31"""
        summary = await adapter.get_earnings_summary("XPEV")
        rev = summary["metrics"]["revenue"]
        assert rev["end_date"] == "2025-12-31", f"Period end mismatch: {rev['end_date']}"
        assert rev["start_date"] == "2025-01-01", f"Period start mismatch: {rev['start_date']}"
        assert rev["form"] == "20-F"
        assert rev["audited"] is True

    @pytest.mark.asyncio
    async def test_aapl_tag_fallback(self, adapter):
        """验证 #11: AAPL 最新年度营收量级 ~$400B，tag 应为 RevenueFrom..."""
        summary = await adapter.get_earnings_summary("AAPL")
        rev = summary["metrics"]["revenue"]
        assert rev["value"] > 350e9, f"AAPL revenue too low: ${rev['value']/1e9:.1f}B"
        assert "RevenueFromContract" in rev["tag_used"], f"Tag should be RevenueFrom..., got {rev['tag_used']}"
        assert rev["end_date"][5:7] == "09", f"AAPL FY ends in Sep, got end={rev['end_date']}"

    @pytest.mark.asyncio
    async def test_xpev_taxonomy_is_usgaap(self, adapter):
        """FPI ≠ IFRS: XPEV 是 FPI 但用 us-gaap"""
        summary = await adapter.get_earnings_summary("XPEV")
        assert summary["taxonomy"] == "us-gaap", f"XPEV uses us-gaap, got {summary['taxonomy']}"
        assert summary["entity_type"] == "foreign_private_issuer"

    @pytest.mark.asyncio
    async def test_nvda_revenue_reasonable(self, adapter):
        """NVDA FY2026 营收应 > $100B（AI 放量）"""
        summary = await adapter.get_earnings_summary("NVDA")
        rev = summary["metrics"]["revenue"]
        assert rev["value"] > 100e9, f"NVDA revenue too low: ${rev['value']/1e9:.1f}B"
        assert summary["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_baba_currency_is_cny(self, adapter):
        """BABA 是 FPI + RMB 记账"""
        summary = await adapter.get_earnings_summary("BABA")
        assert summary["currency"] == "CNY", f"BABA reports in CNY, got {summary['currency']}"
        assert summary["entity_type"] == "foreign_private_issuer"


# ── 跨公司一致性 ──────────────────────────────────────────────

@pytest.mark.sec
class TestCrossCompany:

    @pytest.mark.asyncio
    async def test_currencies_are_mixed(self, adapter):
        """确认系统确实有混合币种——防止未来误把所有公司归一化成 USD"""
        xpev = await adapter.get_earnings_summary("XPEV")
        aapl = await adapter.get_earnings_summary("AAPL")
        currencies = {xpev["currency"], aapl["currency"]}
        assert len(currencies) == 2, f"Expected mixed currencies, got {currencies}"

    @pytest.mark.asyncio
    async def test_traceability(self, adapter):
        """验证 #8: 每个数字带 accession 号可回溯"""
        summary = await adapter.get_earnings_summary("AAPL")
        rev = summary["metrics"]["revenue"]
        accn = rev["accession"]
        assert accn, "Accession number missing"
        assert len(accn) >= 18, f"Accession too short: {accn}"
        # Accession format: 0000320193-25-000079 → can build Archives URL
        parts = accn.split("-")
        assert len(parts) == 3, f"Accession format unexpected: {accn}"


# ── 辅助方法 ──────────────────────────────────────────────────

class TestHelpers:

    def test_tag_aliases_cover_key_metrics(self):
        """确保 alias 表覆盖所有核心指标"""
        required = {"revenue", "net_income", "eps_diluted", "total_assets", "operating_cash_flow"}
        actual = set(_TAG_ALIASES.keys())
        missing = required - actual
        assert not missing, f"Missing tag aliases for: {missing}"

    def test_ticker_to_cik_aapl(self, adapter):
        cik = adapter._ticker_to_cik("AAPL")
        assert cik == "0000320193", f"AAPL CIK wrong: {cik}"

    def test_ticker_to_cik_nvda(self, adapter):
        cik = adapter._ticker_to_cik("NVDA")
        assert cik == "0001045810", f"NVDA CIK wrong: {cik}"

    def test_ticker_to_cik_case_insensitive(self, adapter):
        assert adapter._ticker_to_cik("aapl") == adapter._ticker_to_cik("AAPL")
