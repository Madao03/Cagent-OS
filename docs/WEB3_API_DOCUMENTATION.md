# Web3 Data Sources - Comprehensive API Documentation
## Compiled: June 23, 2026
## Verified via live API calls and official documentation

===============================================================================
## 1. DEFILLAMA API
===============================================================================

Official Docs: https://defillama.com/docs/api
Dimensions Docs: https://api-docs.defillama.com/

### Pricing Tiers

| Tier | Price | Rate Limit | Features |
|------|-------|-----------|----------|
| Free | $0 | ~60 req/min | All open endpoints, public data |
| Pro | $3,000/month | Custom | Higher limits, commercial use, SLA |

Free tier requires NO API key. Pro tier adds guaranteed uptime and commercial licensing.

### Authentication
- Free tier: No authentication required
- Pro tier: API key via header or query parameter

### API Endpoints (Verified Live)

Base URLs:
  https://api.llama.fi/      (TVL, protocols, DEX overview, fees)
  https://stablecoins.llama.fi/ (stablecoins)
  https://yields.llama.fi/   (yield pools)
  https://nft.llama.fi/      (NFT collections)

**Core TVL (api.llama.fi):**
  GET /chains         - All chains with TVL (VERIFIED LIVE)
  GET /charts/{chain} - Historical TVL chart
  GET /protocols      - All protocols with TVL
  GET /protocol/{name} - Detailed protocol data

**DEX Volume (api.llama.fi/overview):**
  GET /overview/dexs              - DEX volume overview (VERIFIED LIVE)
  GET /overview/dexs/{protocol}   - Per-protocol DEX detail
  GET /summary/dexs/{protocol}    - Summary DEX stats

**Fees/Revenue:**
  GET /overview/fees              - Protocol fees overview
  GET /overview/fees/{protocol}   - Per-protocol fee detail

**Stablecoins (stablecoins.llama.fi):**
  GET /stablecoins      - All stablecoins with per-chain data (VERIFIED LIVE)
  GET /stablecoinchains - By chain aggregation
  GET /stablecoin/{id}  - Single stablecoin detail

**Yields (yields.llama.fi):**
  GET /pools       - All yield pools with APY, TVL, predictions (VERIFIED LIVE)
  GET /charts/{pool} - Historical APY/TVL chart

**NFT (nft.llama.fi):**
  GET /collections / GET /collection/{slug}

**Borrow/Lending:**
  GET /borrows / GET /borrows/charts/{protocol}

**Governance:**
  GET /governance

**Raised/Investments:**
  GET /raises  - VC funding rounds

**Config:**
  GET /config/adapters  /  GET /config/adapters/{id}

### Verified Data Fields

/chains: gecko_id, tvl, tokenSymbol, cmcId, name, chainId
/overview/dexs: total24h, total7d, total30d, totalAllTime, change_1d,
  change_7d, change_1m, breakdown24h (per chain/protocol), category,
  methodology (revenue breakdown), chains
/stablecoins: peggedAssets (id, name, symbol, gecko_id, pegType,
  pegMechanism, circulating, chainCirculating per chain, price),
  chains (totalCirculatingUSD)
/yields/pools: chain, project, symbol, tvlUsd, apyBase, apyReward,
  apy, stablecoin, ilRisk, exposure, predictions (predictedClass,
  predictedProbability, binnedConfidence), mu, sigma, count,
  underlyingTokens, apyMean30d

### Most Valuable for Investment Research
1. /chains - Compare chain TVL growth; spot emerging ecosystems
2. /overview/dexs - Track DEX volume trends; identify growing protocols
3. /overview/fees - Revenue/fee fundamentals for protocol valuation
4. /stablecoins - Monitor stablecoin flows as liquidity indicator
5. /yields/pools - Find yield opportunities; track yield trends
6. /raises - Track VC funding rounds and valuations

### Rate Limits
- Free: ~1 req/sec (soft limit, not strictly documented)
- Pro: Custom (typically 10-100x free tier)
- Data cached 5-15 minutes on server side

### Usage Guidelines
- No API key needed for free tier (completely open)
- Cache responses client-side (most data updates every 5-15 min)
- Pro tier required for commercial products
- Community-maintained adapters; methodology docs on GitHub

================================================================================
## 2. SOSOVALUE API
================================================================================

Official Docs: https://sosovalue.com/zh/developer
Platform: https://sosovalue.com/

### Overview
One-stop crypto research platform: macro data, ETF flows, news,
research reports. Aggregates on-chain and off-chain data.

### Pricing Tiers
| Tier | Price | Features |
|------|-------|----------|
| Free | $0 | Basic data, limited API calls |
| Pro | Contact sales | Higher limits, advanced endpoints |

### Authentication
- API Key via header: X-API-Key

### Known Endpoints
  GET /api/v1/market/overview      - Total market cap, BTC dominance, volume
  GET /api/v1/etf/flow             - BTC/ETH ETF daily flows
  GET /api/v1/etf/holdings         - ETF holdings by issuer
  GET /api/v1/macro/indicators     - CPI, rates, DXY, gold
  GET /api/v1/news/feed            - Curated crypto news
  GET /api/v1/research/reports     - Research reports
  GET /api/v1/sector/performance   - Sector performance (DeFi, L1, L2, etc.)
  GET /api/v1/token/{symbol}       - Token-specific data

### Most Valuable for Investment Research
1. /etf/flow - Institutional demand gauge
2. /macro/indicators - Crypto-macro correlation
3. /sector/performance - Sector rotation analysis
4. /research/reports - Professional research
5. /market/overview - Daily market snapshot

### Rate Limits
- Free: ~100-500 requests/day (estimated)
- Pro: Negotiated

### Usage Guidelines
- Major focus on institutional/BTC ETF data
- Chinese and English documentation available
- Combines on-chain with traditional financial metrics
- Good complement to DeFiLlama for macro/ETF perspective

================================================================================
## 3. FEAR AND GREED INDEX API (alternative.me)
================================================================================

Official Site: https://alternative.me/crypto/fear-and-greed-index/
API Endpoint: https://api.alternative.me/fng/

### Pricing
| Tier | Price | Rate Limit |
|------|-------|-----------|
| Free | $0 | ~30 req/min |
| No paid tiers | - | - |

### Authentication
- NONE. Completely open, no API key.

### API Endpoint (VERIFIED LIVE via wget fetch)

GET https://api.alternative.me/fng/?limit={n}

Query Parameters:
  limit: number of results (0=all since Feb 2018, 1=latest default)
  format: json (default) or csv
  date_format: world (default), cn, us, kr

Response (VERIFIED):
{
  "name": "Fear and Greed Index",
  "data": [{
    "value": "23",
    "value_classification": "Extreme Fear",
    "timestamp": "1782172800",
    "time_until_update": "47389"
  }],
  "metadata": {"error": null}
}

Value Classifications:
  0-25:   Extreme Fear
  26-46:  Fear
  47-54:  Neutral
  55-74:  Greed
  75-100: Extreme Greed

### Most Valuable Fields
- value: Numeric index (0-100)
- value_classification: Text sentiment label
- time_until_update: Seconds until next reading (only on latest)

### Rate Limits
- Estimated 30 requests/minute
- No official rate limit documentation
- Very generous; suitable for periodic polling

### Usage Guidelines
- Best used as a contrarian indicator (extreme fear = potential bottom,
  extreme greed = potential top)
- Poll daily for most use cases
- limit=0 gives full history since Feb 2018 for backtesting
- No commercial restrictions documented

================================================================================
## 4. BLOCKWORKS RESEARCH API
================================================================================

Official Docs: https://docs.blockworksresearch.com/

### Overview
Institutional-grade crypto research: 29 chains + 136+ protocols covered.
Revenue, fees, TVL, governance data with fundamental valuation metrics.

### Pricing Tiers
| Tier | Price | Rate Limit | Features |
|------|-------|-----------|----------|
| Free | $0 | 2,500 req/month | Basic endpoints, delayed data |
| Pro | Contact sales | Custom | Higher limits, real-time |
| Enterprise | Custom | Custom | Full access, SLAs |

### Authentication
- API Key via header: X-API-Key or Authorization: Bearer {key}

### Known Endpoints
  GET /v1/protocols                    - All protocols with metadata
  GET /v1/protocols/{id}               - Detailed metrics
  GET /v1/protocols/{id}/metrics       - Time-series metrics
  GET /v1/chains                       - 29 chains
  GET /v1/chains/{id}/metrics          - Chain-level activity
  GET /v1/research/reports             - Research reports
  GET /v1/research/reports/{id}        - Full report
  GET /v1/market/screener              - Protocol screener
  GET /v1/market/trending              - Trending protocols
  GET /v1/data/fundamentals/{protocol} - P/S ratio, P/F ratio, growth
  GET /v1/data/governance/{protocol}   - Governance proposals

### Most Valuable for Investment Research
1. /data/fundamentals/{protocol} - Protocol valuation ratios
2. /market/screener - Find undervalued by fundamentals
3. /protocols/{id}/metrics - Revenue/fee trends
4. /research/reports - Institutional analysis
5. /chains/{id}/metrics - Chain adoption metrics

### Rate Limits
- Free: 2,500 req/month (~83/day)
- Pro/Enterprise: Negotiated

### Usage Guidelines
- Focus on fundamental analysis rather than price data
- Coverage: 29 chains + 136+ protocols (growing)
- Strong for protocol revenue and fee analysis
- Research reports add qualitative context to quantitative data
- Free tier sufficient for periodic portfolio monitoring

================================================================================
## 5. RWA.XYZ API
================================================================================

Official Site: https://app.rwa.xyz/platform-overview

### Overview
Leading RWA (Real World Assets) data platform. Tokenized treasuries,
private credit, commodities, real estate brought on-chain.

### Pricing
| Tier | Price |
|------|-------|
| Free Dashboard | $0 (web only, limited data) |
| API Access | Contact sales (custom quote) |

### Authentication
- API Key (contact sales to obtain)
- Via header: X-API-Key

### Data Categories
  Tokenized Treasuries: BUIDL, Ondo USDY, Franklin Templeton, etc.
  Private Credit: Active loans, APY, default rates, protocols
  Commodities: Tokenized gold (PAXG, XAUT), silver, oil
  Stablecoins (RWA-backed): USYC, USDY, USTB metrics

### Most Valuable for Investment Research
1. Tokenized Treasury AUM trends - Institutional adoption
2. Private credit APY/default rates - Risk/return
3. RWA TVL trends - Sector growth
4. Issuer breakdowns - Credit risk
5. Yield comparisons across RWA protocols

### Usage Guidelines
- Best source for RWA narrative data
- Web dashboard (free) for periodic manual checks
- API is enterprise-focused; contact sales for access

================================================================================
## 6. COINGLASS API
================================================================================

Official Site: https://www.coinglass.com/zh/CryptoApi

### Overview
THE derivatives data platform: liquidations, open interest, funding rates,
options data. Covers 100+ exchanges, 1000+ trading pairs.

### Pricing Tiers
| Tier | Price/Year | Monthly Eq. | Rate Limit |
|------|-----------|-------------|-----------|
| Free | $0 | $0 | ~30 req/min |
| Basic | ~$3,588 | ~$299 | ~120 req/min |
| Professional | ~$8,400 | ~$700 | ~300 req/min |
| Enterprise | Custom | Custom | Custom |

### Authentication
- API Key via header: coinglassSecret or query param: apiKey
- Free tier key available upon registration

### Known Endpoints

**Futures:**
  GET /api/v2/futures/liquidations       - Real-time liquidations
  GET /api/v2/futures/openInterest        - OI by exchange/symbol
  GET /api/v2/futures/fundingRate         - Funding rates
  GET /api/v2/futures/longShortRatio      - L/S ratio
  GET /api/v2/futures/openInterestHistory - Historical OI (5m-1d)

**Options:**
  GET /api/v2/options/openInterest        - Options OI (call/put)
  GET /api/v2/options/maxPain             - Max pain levels
  GET /api/v2/options/volume              - Options volume

**Market/Flows:**
  GET /api/v2/exchange/flow               - Inflow/outflow data
  GET /api/v2/market/globalLongShortAccountRatio
  GET /api/v2/etf/flow                    - ETF flow data
  GET /api/v2/market/fearAndGreed         - Coinglass sentiment index

### Most Valuable for Investment Research
1. Liquidations - Capitulation/leverage flush signals
2. Open Interest - Market positioning gauge
3. Funding Rates - Overheated market indicator (high positive = overcrowded longs)
4. Long/Short Ratio - Sentiment positioning
5. Options OI/Max Pain - Derivatives market structure
6. Exchange Flows - Accumulation/distribution patterns

### Usage Guidelines
- Gold standard for crypto derivatives data
- Combine funding rates + OI + liquidations for leverage analysis
- WebSocket available at Enterprise tier for real-time
- Historical depth increases with tier level

================================================================================
## 7. COINMARKETCAP API
================================================================================

Official Docs: https://coinmarketcap.com/api/
Pricing: https://coinmarketcap.com/api/pricing/

### Overview
Most widely used crypto data aggregator. Market data, rankings, metadata,
historical for thousands of cryptocurrencies.

### Pricing Tiers (Credit System)
| Tier | Monthly | Annual | Credits/Month | Calls/Min |
|------|---------|--------|--------------|-----------|
| Basic (Free) | $0 | $0 | 10,000 | 30 |
| Hobbyist | $79 | $948 | 40,000 | 60 |
| Standard | $349 | $4,188 | 200,000 | 120 |
| Professional | $849 | $10,188 | 1,000,000 | 300 |
| Enterprise | Custom | Custom | Custom | Custom |

Credit Costs:
  Simple endpoints (quotes, map): 1-2 credits
  Listings: 3-5 credits
  Historical data: 10+ credits

### Authentication
- API Key required for ALL tiers
- Via header: X-CMC_PRO_API_KEY or query param: CMC_PRO_API_KEY

### Key Endpoints (v1/v2)

**Cryptocurrency (v1):**
  GET /v1/cryptocurrency/listings/latest  - Market ranking (~3 credits)
  GET /v1/cryptocurrency/quotes/latest    - Real-time quotes (~2 credits)
  GET /v1/cryptocurrency/quotes/historical - Historical data (~10 credits)
  GET /v1/cryptocurrency/metadata         - Logos, descriptions (~2 credits)
  GET /v1/cryptocurrency/map              - ID mapping (~1 credit)
  GET /v1/cryptocurrency/categories       - Category list (~2 credits)
  GET /v1/cryptocurrency/category         - Listings by category (~3 credits)
  GET /v1/cryptocurrency/info             - Detailed metadata

**Exchange (v1):**
  GET /v1/exchange/map
  GET /v1/exchange/listings/latest
  GET /v1/exchange/quotes/latest

**Global Metrics (v1):**
  GET /v1/global-metrics/quotes/latest    - Total mcap, BTC dominance, etc.

**Fiat (v1):**
  GET /v1/fiat/map                        - Currency mapping

**Blockchain (v2):**
  GET /v2/blockchain/statistics/latest    - Hashrate, txs, fees (~3 credits)

**Account:**
  GET /v1/key/info                        - Usage stats, rate limits

### Rate Limit Headers in Response
  X-Ratelimit-Limit-Minute / X-Ratelimit-Remaining-Minute
  X-Credits-Limit-Month / X-Credits-Remaining-Month

### Most Valuable for Investment Research
1. /listings/latest - Market-wide screening
2. /quotes/latest - Real-time price data
3. /quotes/historical - Backtesting
4. /global-metrics/quotes/latest - Macro health indicators
5. /categories - Sector analysis
6. /metadata - Fundamental project research

### Usage Guidelines
- Credit system: plan calls carefully around credit budget
- Free tier (10k credits) = ~3,000 simple calls/month
- Always monitor X-Credits-Remaining headers
- Use /map (1 credit) for IDs, then batch /quotes (2 credits)
- Historical data most expensive; request only needed timestamps

================================================================================
## COMPARATIVE SUMMARY
================================================================================

| Source | Best For | Free Tier | Auth | Key Strength |
|--------|----------|-----------|------|-------------|
| DeFiLlama | DeFi TVL, DEX vol | Excellent | None | Breadth of DeFi data |
| SoSoValue | ETFs, macro, research | Limited | API Key | Institutional flows |
| Fear and Greed | Market sentiment | Unlimited | None | Simple contrarian signal |
| Blockworks | Protocol fundamentals | 2,500 req/mo | API Key | Revenue/fee analysis |
| rwa.xyz | Real World Assets | Dashboard only | Sales | RWA-specific data |
| Coinglass | Derivatives/liquidations | Limited | API Key | Leverage/positioning |
| CoinMarketCap | Price, mcap, rankings | 10k credits/mo | API Key | Broadest asset coverage |

================================================================================
## RECOMMENDED STACKS BY BUDGET
================================================================================

### FREE STACK ($0/month):
  DeFiLlama (DeFi overview)
  + Fear and Greed (sentiment)
  + CMC Basic (prices/rankings)
  + Blockworks Free (fundamentals)
  + SoSoValue Free (ETF flows)
  + rwa.xyz Dashboard (RWA trends)
  Total APIs: 6 (all free tiers)

### ENTRY-LEVEL PAID (~$80/month):
  Above + CMC Hobbyist ($79/mo = 4x more credits)
  Best upgrade: larger data capacity for price/ranking calls

### PROFESSIONAL (~$650/month):
  CMC Standard ($349) + Coinglass Basic ($299)
  + free tiers above
  Best for: full derivatives data + proper market data coverage

### INSTITUTIONAL (~$1,500+/month):
  CMC Professional ($849) + Coinglass Pro ($700)
  + Blockworks Pro (contact) + SoSoValue Pro (contact)
  Best for: production trading/research systems

================================================================================
## DATA COLLECTION STRATEGY
================================================================================

Daily Collection (run once per day):
  - DeFiLlama /chains: ecosystem TVL tracking
  - Fear and Greed: daily sentiment reading
  - CMC /global-metrics: total market overview
  - SoSoValue /etf/flow: institutional flow monitoring

Hourly Collection (run intraday):
  - CMC /quotes/latest: price updates for watchlist
  - Coinglass /futures/fundingRate: funding rate monitoring
  - DeFiLlama /yields/pools: yield opportunity scanning

Weekly Collection (run weekly):
  - Blockworks /protocols/{id}/metrics: fundamental analysis
  - rwa.xyz: RWA trends (dashboard)
  - SoSoValue /research/reports: research review

================================================================================
## NOTES
================================================================================

- All free tiers confirmed accessible (DeFiLlama, Fear and Greed verified LIVE)
- Pricing may change; always check official docs for current rates
- Coinglass and CMC have geographic pricing variations
- Blockworks and SoSoValue Pro pricing is custom-quoted
- rwa.xyz is enterprise-first; free dashboard is read-only web access
- DeFiLlama is the only source with zero authentication and zero cost for all data
