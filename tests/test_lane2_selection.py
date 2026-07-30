"""Selection-layer tests: verify find() returns correct accessions.

Closes the structural blind spot where Tier 1 (fixture-only) tests
verify the extractor but never exercise the document selection logic.

Each entry pins the expected SEC accession for a given quarter — these
are immutable constants. Tests verify that find() picks the right document.
"""
import pytest

# (ticker, quarter_end, expected_accession, label)
# expected_accession=None means "should NOT find a release"
XPEV_QUARTERS = [
    # IPO Aug 2020, first earnings Q3 2020
    ("XPEV", "2020-09-30", "0001193125-20-292178", "Q3 2020"),
    ("XPEV", "2020-12-31", "0001193125-21-078519", "Q4 2020"),
    ("XPEV", "2021-03-31", "0001193125-21-161164", "Q1 2021"),
    ("XPEV", "2021-06-30", "0001193125-21-258067", "Q2 2021"),
    # Q3 2021: real earnings filed Nov 23 (54 days), not Oct 22 (22 days, excluded)
    ("XPEV", "2021-09-30", "0001193125-21-338437", "Q3 2021"),
    ("XPEV", "2021-12-31", "0001193125-22-087333", "Q4 2021"),
    ("XPEV", "2022-03-31", "0001193125-22-159087", "Q1 2022"),
    ("XPEV", "2022-06-30", "0001193125-22-229049", "Q2 2022"),
    # Q3 2022: filed Sep 26 (pre-quarter-end) — correctly NOT FOUND
    ("XPEV", "2022-09-30", None, "Q3 2022"),
    ("XPEV", "2022-12-31", "0001193125-23-074368", "Q4 2022"),
    ("XPEV", "2023-03-31", "0001193125-23-136503", "Q1 2023"),
    ("XPEV", "2023-06-30", "0001193125-23-215945", "Q2 2023"),
    ("XPEV", "2023-09-30", "0001193125-23-277876", "Q3 2023"),
    ("XPEV", "2023-12-31", "0001193125-24-071275", "Q4 2023"),
    ("XPEV", "2024-03-31", "0001193125-24-143932", "Q1 2024"),
    ("XPEV", "2024-06-30", "0001193125-24-203410", "Q2 2024"),
    ("XPEV", "2024-09-30", "0001193125-24-261300", "Q3 2024"),
    ("XPEV", "2024-12-31", "0001193125-25-056220", "Q4 2024"),
    ("XPEV", "2025-03-31", "0001193125-25-117307", "Q1 2025"),
    ("XPEV", "2025-06-30", "0001193125-25-183155", "Q2 2025"),
    ("XPEV", "2025-09-30", "0001193125-25-283869", "Q3 2025"),
    ("XPEV", "2025-12-31", "0001193125-26-117623", "Q4 2025"),
    ("XPEV", "2026-03-31", "0001193125-26-215961", "Q1 2026"),
]

# AAPL 8-K (Item 2.02 path)
AAPL_QUARTERS = [
    ("AAPL", "2025-09-27", "0000320193-25-000077", "Q4 FY2025"),
    ("AAPL", "2025-12-27", "0000320193-26-000005", "Q1 FY2026"),
    ("AAPL", "2026-03-28", "0000320193-26-000011", "Q2 FY2026"),
]


@pytest.mark.sec
class TestSelectionXPEV:
    """Verify find() selects correct accessions for XPEV (22 quarters)."""

    @pytest.mark.parametrize("ticker,quarter_end,expected_acc,label", XPEV_QUARTERS)
    def test_find_returns_correct_accession(self, ticker, quarter_end, expected_acc, label):
        import asyncio
        from cagent_os.data_layer.lane2.classifier import EarningsReleaseFinder

        async def _find():
            finder = EarningsReleaseFinder()
            return await finder.find(ticker, quarter_end)

        result = asyncio.run(_find())

        if expected_acc is None:
            # Should NOT find a release (Q3 2022 — pre-quarter-end filing)
            assert result is None or not result.get("found"), \
                f"{label}: expected NOT FOUND, but got {result}"
        else:
            assert result is not None, \
                f"{label}: find() returned None"
            assert result.get("found"), \
                f"{label}: find() returned found=False"
            actual = result["accession"]
            assert actual == expected_acc, \
                f"{label}: expected {expected_acc}, got {actual} " \
                f"(score={result.get('conf')}, date={result.get('filing_date')})"


@pytest.mark.sec
class TestSelectionAAPL:
    """Verify find() selects correct 8-K accessions (Item 2.02 path)."""

    @pytest.mark.parametrize("ticker,quarter_end,expected_acc,label", AAPL_QUARTERS)
    def test_find_returns_correct_accession(self, ticker, quarter_end, expected_acc, label):
        import asyncio
        from cagent_os.data_layer.lane2.classifier import EarningsReleaseFinder

        async def _find():
            finder = EarningsReleaseFinder()
            return await finder.find(ticker, quarter_end)

        result = asyncio.run(_find())

        assert result is not None, f"{label}: find() returned None"
        assert result.get("found"), f"{label}: find() returned found=False"
        actual = result["accession"]
        assert actual == expected_acc, \
            f"{label}: expected {expected_acc}, got {actual}"
