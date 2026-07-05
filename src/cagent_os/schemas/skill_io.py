"""Skill I/O Schemas — Pydantic v2 contracts for all core skills.

Phase 2e: Each skill's expected output structure is formalized here.
These serve as both documentation and (future) runtime validation targets.

Schema design principles:
  - lenient_by_default — Optional[...] everywhere; partial output is valid
  - human_readable — str timestamps, natural-language descriptions
  - composable — nested sub-models for reuse across skills
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════
# Shared sub-models
# ══════════════════════════════════════════════════════════════════════

class DataSourceReference(BaseModel):
    """A single data point with provenance."""
    indicator: str = ""        # e.g. "CPI YoY", "Nonfarm Payrolls"
    value: Optional[float] = None
    unit: str = ""             # e.g. "%", "thousands"
    date: str = ""             # observation date YYYY-MM-DD
    source: str = ""           # "FRED", "jin10", "fin-skill", "web"


class ConfidenceAnnotation(BaseModel):
    """Confidence level for a claim or prediction."""
    level: str = "medium"      # "high" | "medium" | "low"
    rationale: str = ""        # why this confidence level


# ══════════════════════════════════════════════════════════════════════
# Macro Analysis
# ══════════════════════════════════════════════════════════════════════

class ShortTermMacro(BaseModel):
    """Short-term macro assessment (≤3 months)."""
    liquidity_condition: str = ""      # "loose" | "neutral" | "tight"
    onrrp_trend: str = ""              # e.g. "$6.48T, declining"
    tga_impact: str = ""               # e.g. "TGA drawdown → liquidity injection"
    credit_impulse: str = ""           # e.g. "M1/M2 spread widening"
    market_signals: list[str] = Field(default_factory=list)
    overall: str = ""                  # 1-sentence synthesis


class MediumTermMacro(BaseModel):
    """Medium-term macro assessment (3M-2Y)."""
    pmi_headline: Optional[float] = None       # ISM Mfg PMI value
    pmi_services: Optional[float] = None       # ISM Services PMI value
    pmi_sub_indices: dict[str, Optional[float]] = Field(default_factory=dict)
    inventory_cycle: str = ""          # e.g. "passive inventory build → early slowdown"
    cpi_ppi_spread: Optional[float] = None     # CPI - PPI delta
    profit_margin_signal: str = ""     # "expanding" | "compressing" | "turning"
    employment_demand: str = ""        # "expanding" | "stable" | "contracting"
    employment_supply: str = ""        # "expanding" | "stable" | "contracting"
    employment_matching: str = ""      # "good" | "tight" | "loose"
    wage_pressure: str = ""            # "rising" | "stable" | "falling"
    policy_stance: str = ""            # "tightening" | "easing" | "neutral"
    policy_cycle_match: str = ""       # "matched" | "lagging" | "leading"
    cycle_position: str = ""           # 1-sentence synthesis
    confidence: str = "medium"


class LongTermMacro(BaseModel):
    """Long-term structural assessment (>2 years)."""
    policy_direction: str = ""
    industrial_policy: str = ""
    trade_dynamics: str = ""
    fiscal_health: str = ""
    demographic_trend: str = ""
    technology_position: str = ""


class MacroAnalysisInput(BaseModel):
    """Task description for macro analysis — what to analyze."""
    tickers_or_markets: list[str] = Field(default_factory=list)
    time_horizon_focus: str = "medium"   # "short" | "medium" | "long" | "all"
    specific_question: str = ""          # e.g. "Is the Fed about to pivot?"


class MacroAnalysisOutput(BaseModel):
    """Structured output from macro-analysis skill."""
    skill: str = "macro-analysis"
    generated_at: str = Field(default_factory=_now_iso)
    short_term: Optional[ShortTermMacro] = None
    medium_term: Optional[MediumTermMacro] = None
    long_term: Optional[LongTermMacro] = None
    geopolitical_risks: list[str] = Field(default_factory=list)
    cross_market_signals: dict[str, str] = Field(default_factory=dict)  # asset → direction
    implication_for_risk_assets: str = ""
    key_watchpoints: list[str] = Field(default_factory=list)
    data_sources: list[DataSourceReference] = Field(default_factory=list)
    confidence: str = "medium"  # overall confidence
    raw_markdown: str = ""      # full markdown output (backward compat)


# ══════════════════════════════════════════════════════════════════════
# US Stock Analysis
# ══════════════════════════════════════════════════════════════════════

class CyclicalTrapCheck(BaseModel):
    """Cyclical stock traps: 5 signals that distinguish value from value traps."""
    pe_compression: bool = False     # PE has compressed >30% from peak
    roe_divergence: bool = False     # ROE declining while PE looks cheap
    capex_cycle: bool = False        # Heavy CAPEX at cycle peak
    inventory_build: bool = False    # Inventory building faster than revenue growth
    guidance_cut: bool = False       # Recent guidance cut or estimate downgrades
    trap_risk: str = ""              # "high" | "medium" | "low"
    trap_signals_active: list[str] = Field(default_factory=list)
    explanation: str = ""


class UsStockAnalysisInput(BaseModel):
    ticker: str = ""
    analysis_depth: str = "standard"  # "quick" | "standard" | "deep"
    specific_question: str = ""


class UsStockAnalysisOutput(BaseModel):
    skill: str = "us-stock-analysis"
    generated_at: str = Field(default_factory=_now_iso)
    ticker: str = ""
    company_name: str = ""
    # Layers
    layer1_normal: str = ""            # Normal-state: financials + valuation
    layer2_abnormal: str = ""          # Abnormal-state: divergence analysis
    layer3_blackbox: str = ""          # Black-box: price/volume correlations
    # Cyclical trap
    cyclical_trap: Optional[CyclicalTrapCheck] = None
    # Valuation
    dcf_implied_value: Optional[float] = None
    pe_forward: Optional[float] = None
    pe_ttm: Optional[float] = None
    # Red team
    red_team_challenges: list[str] = Field(default_factory=list)
    # Synthesis
    investment_thesis: str = ""
    key_risks: list[str] = Field(default_factory=list)
    recommendation: str = ""           # "accumulate" | "hold" | "reduce" | "avoid"
    confidence: str = "medium"
    data_sources: list[DataSourceReference] = Field(default_factory=list)
    raw_markdown: str = ""


# ══════════════════════════════════════════════════════════════════════
# Crypto Analysis
# ══════════════════════════════════════════════════════════════════════

class CryptoCyclePosition(BaseModel):
    """Crypto cycle indicators."""
    mvrv_z: Optional[float] = None           # MVRV Z-Score
    fear_greed_index: Optional[int] = None   # 0-100
    puell_multiple: Optional[float] = None
    funding_rate: Optional[float] = None     # perpetual funding rate
    stablecoin_mcap_trend: str = ""          # "expanding" | "stable" | "contracting"
    cycle_phase: str = ""                    # "accumulation" | "bull" | "distribution" | "bear"


class CryptoAnalysisInput(BaseModel):
    asset: str = ""           # e.g. "BTC", "ETH", "SOL"
    analysis_depth: str = "standard"
    specific_question: str = ""


class CryptoAnalysisOutput(BaseModel):
    skill: str = "crypto-analysis"
    generated_at: str = Field(default_factory=_now_iso)
    asset: str = ""
    # Layers
    layer1_normal: str = ""
    layer2_abnormal: str = ""
    layer3_blackbox: str = ""
    # Cycle
    cycle_position: Optional[CryptoCyclePosition] = None
    # Red team
    red_team_challenges: list[str] = Field(default_factory=list)
    # Synthesis
    investment_thesis: str = ""
    key_risks: list[str] = Field(default_factory=list)
    macro_correlation: str = ""         # how macro affects this asset
    recommendation: str = ""           # "accumulate" | "hold" | "reduce" | "avoid"
    confidence: str = "medium"
    data_sources: list[DataSourceReference] = Field(default_factory=list)
    raw_markdown: str = ""


# ══════════════════════════════════════════════════════════════════════
# Content Triage
# ══════════════════════════════════════════════════════════════════════

class TriageScores(BaseModel):
    """Five-dimension scoring for a single article."""
    relevance: int = 0          # 0-2: 他对我的投资清单有用吗
    novelty: int = 0            # 0-2: 有我不知道的新信息吗
    judgment_impact: int = 0    # 0-2: 会影响我的判断吗
    framework_value: int = 0    # 0-2: 有可复用的分析框架吗
    source_quality: int = 0     # 0-2: 来源可靠吗
    total: int = 0              # 0-10 sum
    grade: str = "C"            # "A" | "B" | "C"
    evidence: dict[str, str] = Field(default_factory=dict)  # dimension → quote from article


class TriageEntry(BaseModel):
    """One row in the triage ledger."""
    date: str = ""
    title: str = ""
    url: str = ""
    source: str = ""
    scores: TriageScores = Field(default_factory=TriageScores)
    related_assets: list[str] = Field(default_factory=list)
    one_line_reason: str = ""


class ContentTriageInput(BaseModel):
    urls_or_articles: list[str] = Field(default_factory=list)
    force_rescore: bool = False  # re-score even if previously triaged


class ContentTriageOutput(BaseModel):
    skill: str = "content-triage"
    generated_at: str = Field(default_factory=_now_iso)
    entries: list[TriageEntry] = Field(default_factory=list)
    summary: str = ""           # e.g. "3 A, 2 B, 1 C — focus on #1 and #3"
    ledger_appended: bool = False
    raw_markdown: str = ""


# ══════════════════════════════════════════════════════════════════════
# Crypto Stock Analysis (MSTR / COIN / Miners)
# ══════════════════════════════════════════════════════════════════════

class MnavAnalysis(BaseModel):
    """MSTR mNAV (market-cap to NAV) analysis."""
    mnav_ratio: Optional[float] = None     # market-cap / BTC holdings value
    btc_holdings: Optional[float] = None   # BTC count
    avg_cost_basis: Optional[float] = None
    premium_discount: str = ""             # "premium" | "parity" | "discount"
    strc_status: str = ""                  # STRC instrument status
    flywheel_phase: str = ""               # "accelerating" | "coasting" | "decelerating" | "stalled"
    risk_signals: list[str] = Field(default_factory=list)


class DeathSpiralPhase(BaseModel):
    """STRC three-layer death spiral phase tracking."""
    current_phase: str = ""       # "normal" | "phase1_anchor_break" | "phase2_cost_trap" | "phase3_flywheel_fracture"
    phase1_triggered: bool = False   # anchor break: price below par
    phase2_triggered: bool = False   # cost trap: dividend forced up monthly
    phase3_triggered: bool = False   # flywheel fracture: mNAV < 1x, ATM = $0
    dividend_rate: Optional[float] = None       # current STRC dividend rate %
    monthly_adjustment_bps: Optional[float] = None  # latest monthly adjustment in bps
    consecutive_months_rising: int = 0           # months of consecutive dividend increases
    worst_case_dividend: Optional[float] = None  # projected dividend if trend continues
    ust_comparison_note: str = ""   # key difference from UST: gradual repricing vs overnight collapse


class SignalMatrixItem(BaseModel):
    """One signal with bull and bear interpretation (from MSTR signal tracking framework)."""
    signal_name: str = ""          # e.g. "股息暂停", "ATM增发$0", "mNAV趋势"
    current_value: str = ""        # current observed value
    bull_interpretation: str = ""  # what this means if you're bullish
    bear_interpretation: str = ""  # what this means if you're bearish
    tracking_frequency: str = ""   # "daily" | "weekly" | "monthly"


class LeverageStressTest(BaseModel):
    """MSTR leverage stress scenarios."""
    current_leverage_ratio: Optional[float] = None    # total_debt / total_assets
    btc_down_30pct_leverage: Optional[float] = None   # projected leverage if BTC -30%
    btc_down_50pct_leverage: Optional[float] = None   # projected leverage if BTC -50%
    liquidation_waterfall: str = ""                    # "普通债 → 优先股 → 普通股" buffer analysis
    can_issue_equity_at_mnav_1x: bool = True          # can still dilute to deleverage?


class StratusFlywheel(BaseModel):
    """MSTR's STRC flywheel self-reinforcing cycle analysis — enhanced with death spiral tracking."""
    btc_trend: str = ""          # "up" | "flat" | "down"
    strc_face_value: str = ""    # "at par" | "below par" | "above par"
    atm_issuance: str = ""       # "active" | "paused" | "exhausted"
    flywheel_state: str = ""     # "accelerating" | "decelerating" | "stalled"
    break_conditions: list[str] = Field(default_factory=list)
    death_spiral: Optional[DeathSpiralPhase] = None
    signal_matrix: list[SignalMatrixItem] = Field(default_factory=list)
    leverage_stress: Optional[LeverageStressTest] = None
    # ── STRC specific thresholds ──
    strc_vwap: Optional[float] = None            # current monthly VWAP
    strc_vwap_trend: str = ""                     # "above_100" | "95_99" | "below_95"
    dividend_adjustment_triggered: bool = False   # did this month trigger a +25 or +50 bps adjustment?
    flywheel_five_point_checklist: dict[str, bool] = Field(default_factory=dict)
    # checklist keys: financing_flywheel_healthy, leverage_solvent,
    #   dividend_cost_tracking, reflexivity_fragility, institutional_concentration


class CryptoStockAnalysisInput(BaseModel):
    ticker: str = ""          # "MSTR" | "COIN" | mining tickers
    analysis_type: str = ""   # "mnav" | "exchange" | "miner" | "auto"


class CryptoStockAnalysisOutput(BaseModel):
    skill: str = "crypto-stock-analysis"
    generated_at: str = Field(default_factory=_now_iso)
    ticker: str = ""
    company_name: str = ""
    analysis_type: str = ""
    # ── Step 0: instrument deconstruction ──
    instrument_identity: str = ""     # what financial instrument is this ticker?
    cashflow_mechanism: str = ""      # where does money come from? who pays whom?
    pricing_mechanism: str = ""       # market supply/demand or active par anchor?
    control_rights: str = ""          # who can change key parameters?
    # MSTR-specific
    mnav: Optional[MnavAnalysis] = None
    flywheel: Optional[StratusFlywheel] = None
    # COIN-specific
    exchange_revenue_mix: dict[str, Optional[float]] = Field(default_factory=dict)
    # Miner-specific
    miner_hashrate: Optional[float] = None
    miner_cost_per_btc: Optional[float] = None
    # Shared
    macro_correlation: str = ""
    btc_price_sensitivity: str = ""       # e.g. "$1 BTC move → N% stock move"
    red_team_challenges: list[str] = Field(default_factory=list)
    recommendation: str = ""
    confidence: str = "medium"
    data_sources: list[DataSourceReference] = Field(default_factory=list)
    raw_markdown: str = ""


# ══════════════════════════════════════════════════════════════════════
# Content Assetize
# ══════════════════════════════════════════════════════════════════════

class AssetFact(BaseModel):
    """A single verifiable fact extracted from an article."""
    type: str = "fact"
    statement: str = ""
    value: Optional[float] = None
    unit: str = ""
    time_period: str = ""
    source_quote: str = ""           # exact quote from article
    source_article: str = ""
    confidence: str = "high"
    cross_validatable: bool = False
    tags: list[str] = Field(default_factory=list)


class AssetOpinion(BaseModel):
    """A subjective claim, forecast, or investment view."""
    type: str = "opinion"
    statement: str = ""
    author: str = ""
    confidence_level: str = "explicit"
    time_horizon: str = ""
    counterpoint: str = ""           # opposing view or risk
    tags: list[str] = Field(default_factory=list)


class AssetFramework(BaseModel):
    """A reusable analytical structure (taxonomy, model, checklist)."""
    type: str = "framework"
    name: str = ""                   # a short, quotable name
    description: str = ""
    steps: list[str] = Field(default_factory=list)
    applicable_to: list[str] = Field(default_factory=list)
    source_article: str = ""
    reusability: str = "medium"      # "high" | "medium" | "low"


class ArticleReference(BaseModel):
    """Metadata about the source article."""
    title: str = ""
    url: str = ""
    source: str = ""
    triage_score: int = 0
    assetized_at: str = Field(default_factory=_now_iso)


class ContentAssetizeInput(BaseModel):
    """Input for content assetization."""
    article_path: str = ""           # path relative to project root
    force_reprocess: bool = False


class ContentAssetizeOutput(BaseModel):
    """Structured output from content-assetize skill."""
    skill: str = "content-assetize"
    generated_at: str = Field(default_factory=_now_iso)
    article: ArticleReference = Field(default_factory=ArticleReference)
    facts: list[AssetFact] = Field(default_factory=list)
    opinions: list[AssetOpinion] = Field(default_factory=list)
    frameworks: list[AssetFramework] = Field(default_factory=list)
    stats: dict[str, int] = Field(default_factory=dict)
    raw_markdown: str = ""


# ══════════════════════════════════════════════════════════════════════
# DeFi Analysis
# ══════════════════════════════════════════════════════════════════════

class DefiFundamentals4D(BaseModel):
    """Four-dimension DeFi fundamental analysis."""
    # Demand
    dau_mau: str = ""              # active user trends
    retention_30d_90d: str = ""    # user retention
    fee_sources: str = ""          # real trading vs arbitrage vs wash
    real_demand_assessment: str = ""  # after removing incentives and arbitrage
    # Supply
    tvl_current: Optional[float] = None
    tvl_trend: str = ""            # "growing" | "stable" | "declining"
    market_share_pct: Optional[float] = None
    cross_chain_tvl_distribution: dict[str, Optional[float]] = Field(default_factory=dict)
    saturation_assessment: str = ""
    # Revenue
    fees_annualized: Optional[float] = None
    protocol_revenue: Optional[float] = None
    real_yield: str = ""
    revenue_growth_qoq: Optional[float] = None
    incentives_zero: bool = False  # True = no token subsidies → real PMF signal
    # Tokenomics
    total_supply: Optional[float] = None
    circulating_supply: Optional[float] = None
    unlock_schedule_type: str = ""  # "linear" | "cliff" | "completed" | "unknown"
    monthly_unlock_value: Optional[float] = None
    staking_ratio: Optional[float] = None
    buyback_burn_mechanism: str = ""


class DefiValuation3Layer(BaseModel):
    """Three-layer valuation for DeFi protocols."""
    # Layer 1: Peer comps
    peer_comps: list[dict[str, Any]] = Field(default_factory=list)  # [{name, ps, mcap_tvl, generation}]
    peer_implied_range: str = ""      # e.g. "$1.2B - $2.5B"
    # Layer 2: Architecture premium
    secondary_identity: str = ""      # e.g. "L1 + Perp DEX + CEX challenger"
    premium_factors: list[str] = Field(default_factory=list)
    premium_justified: str = ""       # "yes" | "partial" | "no"
    premium_adjusted_range: str = ""
    # Layer 3: TAM replacement
    tam_market_size: Optional[float] = None
    penetration_scenarios: dict[str, Optional[float]] = Field(default_factory=dict)
    tam_upside_note: str = ""


class DefiAnalysisInput(BaseModel):
    """Input for DeFi protocol analysis."""
    protocol_name: str = ""
    chain: str = ""              # "Ethereum" | "Solana" | "multi-chain" | etc.
    category: str = ""           # "Lending" | "DEX" | "LSD" | "Perp DEX" | etc.
    analysis_depth: str = "standard"  # "quick" | "standard" | "deep"


class DefiAnalysisOutput(BaseModel):
    """Structured output from defi-analysis skill."""
    skill: str = "defi-analysis"
    generated_at: str = Field(default_factory=_now_iso)
    protocol_name: str = ""
    category: str = ""
    chain: str = ""
    generation: str = ""           # "Gen1" | "Gen2" | "Gen3"
    # Positioning
    one_liner: str = ""            # what problem, who competes, why win
    # Fundamentals
    fundamentals: DefiFundamentals4D = Field(default_factory=DefiFundamentals4D)
    # Valuation
    valuation: DefiValuation3Layer = Field(default_factory=DefiValuation3Layer)
    mcap_tvl_ratio: Optional[float] = None
    mcap_tvl_judgment: str = ""    # "undervalued" | "typical" | "premium" | "bubble"
    # Scenarios
    bear_case_valuation: Optional[float] = None
    base_case_valuation: Optional[float] = None
    bull_case_valuation: Optional[float] = None
    # Catalysts & Risks
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    pitfalls_triggered: list[str] = Field(default_factory=list)  # which common pitfalls detected
    # Synthesis
    investment_thesis: str = ""    # one-sentence investment logic
    recommendation: str = ""       # "accumulate" | "hold" | "reduce" | "avoid"
    confidence: str = "medium"
    data_sources: list[DataSourceReference] = Field(default_factory=list)
    raw_markdown: str = ""


# ══════════════════════════════════════════════════════════════════════
# Investment Memo
# ══════════════════════════════════════════════════════════════════════

class FRMultiplierValuation(BaseModel):
    """F/R乘数法 — L1-native valuation (FDV / REV)."""
    fdv: Optional[float] = None
    annual_revenue: Optional[float] = None
    fr_multiple: Optional[float] = None
    mev_purity: str = ""             # "high" | "medium" | "low"
    comparable_chains: list[dict[str, Any]] = Field(default_factory=list)
    adjusted_target_fdv: Optional[float] = None
    structural_undervaluation: bool = False


class DualTrackValuation(BaseModel):
    """Dual-track cross-validation: P/S (bottom-up) + F/R (top-down)."""
    ps_bottom_up_range: str = ""
    fr_top_down_range: str = ""
    cross_validation_note: str = ""
    preferred_track: str = ""        # "ps" | "fr" | "both_converge" | "diverge_significantly"


class PositionSizingMatrix(BaseModel):
    """3×3 position sizing: valuation × catalyst."""
    valuation_axis: str = ""         # "cheap" | "fair" | "expensive"
    catalyst_axis: str = ""          # "strong_positive" | "neutral" | "negative"
    base_position_pct: Optional[float] = None
    left_side_add_trigger: str = ""
    right_side_add_trigger: str = ""
    hard_cap_pct: Optional[float] = None
    stop_loss_conditions: list[str] = Field(default_factory=list)


class MemoSection(BaseModel):
    """One section of the investment memo."""
    section_id: str = ""             # "0" | "I" | ... | "VII"
    title: str = ""
    content: str = ""
    key_claims: list[str] = Field(default_factory=list)
    data_citations: list[str] = Field(default_factory=list)
    confidence: str = "medium"


class InvestmentMemoInput(BaseModel):
    """Input for memo generation."""
    project_name: str = ""
    asset_type: str = ""             # "crypto_token" | "equity" | "defi_protocol" | "l1"
    ticker: str = ""
    template: str = "standard"
    specific_question: str = ""


class InvestmentMemoOutput(BaseModel):
    """Structured output from investment-memo skill."""
    skill: str = "investment-memo"
    generated_at: str = Field(default_factory=_now_iso)
    project_name: str = ""
    ticker: str = ""
    executive_summary: str = ""
    sections: list[MemoSection] = Field(default_factory=list)
    dual_track_valuation: Optional[DualTrackValuation] = None
    fr_multiplier: Optional[FRMultiplierValuation] = None
    ps_target_range: str = ""
    position_sizing: Optional[PositionSizingMatrix] = None
    investment_thesis: str = ""
    key_risks: list[str] = Field(default_factory=list)
    recommendation: str = ""         # "buy" | "hold" | "sell" | "pass"
    confidence: str = "medium"
    version: str = "1.0"
    revision_log: list[str] = Field(default_factory=list)
    data_sources: list[DataSourceReference] = Field(default_factory=list)
    raw_markdown: str = ""
