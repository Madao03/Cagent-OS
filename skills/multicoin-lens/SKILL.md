---
name: multicoin-lens
description: |
  Multicoin Capital 投资框架 — 八大投资主题、Solana Internet Capital Markets 论、
  RWA 四模型、市场微观结构(ACE/逆向选择/条件流动性)。分析 crypto 项目时提供
  Multicoin 视角作为分析补充。
category: research
---

# Multicoin Capital 投资框架

> "Blockchains are the first-principles-correct technology to move money, coordinate and program capital formation, and power global financial markets."
> — Kyle Samani & Tushar Jain

## 何时触发

- 分析 crypto 项目/赛道，需要 VC 级投资视角
- 用户问"Multicoin 怎么看这个赛道""这个项目符合哪类投资主题"
- 需要判断一个 crypto 项目是否属于"Multicoin 会投的方向"
- 评估 Solana 生态项目（Solana 论是 Multicoin 最核心的单一论点）
- 分析 RWA/DeFi/DePIN/稳定币赛道
- 分析链上市场微观结构问题（MEV/有毒订单流/AMM 设计）
- ⚠️ 分析美股/CeFi 时不需要加载

---

## 八大投资主题（2026.02）

### 1) Fintech 4.0
稳定币 + 区块链是几十年来支付和结算的首次重大创新。挑战卡网络和大型银行的垄断。

**投资方向：** 专业稳定币 fintech、压缩金融科技栈的产品、面向全球消费者/企业的稳定币通道

### 2) DeFi Mullet（DeFi 鲻鱼头）
DeFi 栈成熟 + 软件开发壁垒下降 → 价值在上中下游均可捕获。前端拥有客户关系，后端享受规模经济，中间件连接两端。

**投资方向：** 前端订单流引擎（Phantom/Fuse/Robinhood）、DeFi 上构建的上市公司股权（Coinbase/Morpho）、DeFi 中间件（LI.FI/Fun.xyz/Yield.xyz）、DeFi 协议（Kamino/Drift/Aave/Ethena）

### 3) Financial Globalization（金融全球化）
传统股票、外汇、利率、债务市场仅在部分地区可及。区块链实现全球访问。

**投资方向：** 流动市场代币化（Paxos）、合成衍生品协议（Drift/Hyperliquid/Lighter）、照亮暗池市场（BAXUS/Triumph）、创造新市场（Kalshi/Sway）、推动链上市场微观结构（DFlow/Jito/FastLane）

### 4) More Efficient Borrow/Lend
链上借贷让资金和抵押品在全球借贷双方之间直接流动，无需依赖地理/人脉。

**投资方向：** 借贷协议（Kamino/Aave）、新兴金库协议 + DeFi 主经纪商

### 5) Entertainment Finance（娱乐金融）
当"美国梦"遥不可及时，人们开始 take bigger swings。加密是这些风险承担者更公开、中介抽成更少的市场。

**投资方向：** 降低娱乐/degen 经济抽成的项目（Cheddr/Novig）

### 6) Programmable Ownership（可编程所有权）
设计良好的 Token 是超级力量——赋能 DePIN、加密关联股权、在线市场中的可编程所有权。

**投资方向：** DePIN（Helium/Hivemapper/Render/io.net/Geodnet/Pipe/Gradient）、互联网劳动力市场（CrunchDAO/Fuse）、DAO 管理的虚拟市场（Jito/Drift/Kamino）

### 7) Credibly-Neutral Blockchains（可信中立区块链）
基础层的可信中立性极其重要。金融市场在竞争者感到安全的共享系统上增长更快。

**已投资：** APT, SOL, SEI
**核心观点：** 企业链难以吸引第三方建设者 — "E*TRADE 不会想在 Robinhood 的链上建"，"Adyen 会对 Stripe Tempo 链保持怀疑"。价值捕获将向上移动至应用层。

### 8) Cryptographic Primitives（密码学原语）
稳定币让 AI Agent 可以收发支付；密码学原语让我们无需建立大规模数据蜜罐即可验证线上真实性。

**投资方向：** Zama, Fhenix, zkMe

---

## Solana 论：Internet Capital Markets（2025.01 第五版）

这是 Multicoin 最核心的单一论点。Kyle Samani 撰写。

### 核心主张

Solana 可以在核心性能指标（延迟等）上超越传统金融巨头（NYSE/NASDAQ/CME/JPM/GS/MS/Visa/Mastercard），同时保持区块链的核心属性：
- 原子可组合性
- 用户/开发者/验证者的无许可访问

### 两个看似矛盾但可同时实现的目标
1. **将终端用户金融服务费用降低 90-99%**
2. **捕获比传统金融巨头更多的总市值**

### 支付是引流品，MEV 是利润中心
- 支付是区块链的 loss leader——gas 费接近零，即使 Solana 全年稳定在 50,000 TPS，总 gas 成本仅 $1.5B
- **利润来自 MEV**——资产价格波动自然产生 MEV，Solana 生态捕获这部分价值
- Q4 2024: Solana REV（不含通胀）超 $800M，年化 $3.2B。一年前近乎 $0

### 条件流动性（Conditional Liquidity, CL）
> Multicoin 认为这是 2018 年 Uniswap x*y=k AMM 以来 DeFi 最重要的功能性改进。

**机制：** 流动性仅在 taker 订单被已知前端（Phantom/Backpack/Drift/Kamino 等）背书时才可成交。保证 bot 无法消耗 CL，MM 不会被 stale quotes pick off。

**类比：** Robinhood 一直以来为客户提供优于 NBBO 的价格——因为 MM 有统计依据相信 Robinhood 用户比 Citadel 更不具毒性。

**预期影响：** CL 将重塑 DeFi 中关于 UX、spread、MEV 的所有讨论。

### TAM 三向扩展
1. DeFi 协议持续成熟 → 新功能 → 新 MEV 机会
2. 原生链上新金融市场（算力、电信、能源）
3. 更多资产上链：memecoin → 美股 → 一切

---

## RWA: 四种上链模型（2026.03）

> "行业把 RWA 同质化为单一类别是错的。股票、外汇、信用、大宗、国债、地产的结算/托管/流动性/监管需求完全不同。"

### 模型 1 — 合成衍生品（Synthetic Derivatives）
追踪 RWA 价格但不持有底层资产。永续合约通过预言机跟踪外部价格，链上用稳定币/加密资产结算。

**代表：** Hyperliquid, Ostium, Lighter
**优点：** 24/7 交易，即时结算，无需中介
**缺点：** 不持实际资产（无投票权/股息），需信任预言机，资金费率侵蚀回报

### 模型 2 — 包裹资产/Wrapper（Custody Model）
受监管实体（基金/SPV/信托）持有链下 RWA → 向终端用户发行收据 Token。

三种子类：直接托管（Dinari 代币化股票）、池化基金份额（Ondo OUSG/Franklin Templeton BENJI）、证券化资产池（Centrifuge 发票融资/Goldfinch 信用池）

### 模型 3 — 抵押借贷（Collateralized Borrowing）
用链下 RWA 作为链上借贷抵押品。不需完全代币化，支持风险分层。

**代表：** Kamino + Anchorage 合作, Sky RWA vaults, Figure Markets HELOC
**缺陷：** 法律结构复杂，清算通过法院系统（非链上自动），抵押品不可跨 DeFi 组合

### 模型 4 — 主链上发行（Primary Onchain Issuance）
Token 即证券本身，非衍生品/包裹。区块链作为官方账本。

**Multicoin 北极星：** 这是"最纯净的 crypto-native RWA 版本"

### 各资产类别路径判断

| 资产类别 | 主导模型 | Multicoin 观点 |
|:---|:---|:---|
| 国债/货币基金 | Model 2 | 短期不会改变，美国财政部不会很快在链上发债 |
| 私募信用 | Model 2 → 可能演进到 Model 4 | 更碎片化、监管更轻，天然适合链上 |
| 公开股票 | Model 1（合成）大爆发 + Model 2（包裹）进展慢 | 合成 perps 增长爆炸性；IPO 前合成交易已出现 |
| 大宗商品 | Model 1（合成）主导 | 实物存储成本高，合成更实用。数字原生商品（算力/带宽/存储）天然是 Model 4 |
| 外汇 | Model 1（合成） | 稳定币已是"包裹法币"。长尾货币稳定币是未开发机会 |

---

## 市场微观结构：ACE + 逆向选择（2026.02-03 三部曲）

### ACE: Application Controlled Execution
核心思想：**应用控制执行可以创造 Token 捕获价值的新方式。**

### 逆向选择：Adverse Selection
**链上交易没有类似 TradFi 的自然分层机制**——散户浏览器钱包、机构程序化交易、searcher 套利，在公开 mempool 中看起来完全一样。没有 broker/账户类型/KYC 等中介功能来区分零售与专业交易者。

**后果：** 有毒订单流 → MM 扩大价差 → 所有人支付更高成本

**毒性测量窗口：** 几微秒到 10 分钟不等，取决于资产。MM 能在一小时内平仓 → 不认为你有毒。流动性越差 → 窗口越长。

**解决路径：**
- 条件流动性（CL）—— DFlow，仅在非毒性订单时提供流动性
- Solana MCL —— 将价格发现推向边缘，降低单个节点被抢先的概率
- 应用层分段 —— 通过前端/钱包背书区分订单流

### RWA 与逆向选择的联系
DeFi 花了多年优化 AMM 市场结构用于长尾代币——这对内部加密交易有用，但可能不适用于 RWA。**RWA 的流动性、价格发现和风险管理机制全然不同，且 MM 愿意报紧价差。**

---

## 关键投资组合速查

| 类别 | 代表项目 |
|:---|:---|
| L1 | Solana (SOL), Aptos (APT), Sei (SEI) |
| DeFi 协议 | Drift, Kamino, Jito, Aave, Ethena, Hyperliquid, Lighter |
| 钱包/前端 | Phantom, Fuse Wallet, Backpack |
| DePIN | Helium, Hivemapper, Render, io.net, Geodnet |
| 稳定币/支付 | p2p.me, El Dorado, Sling Money |
| 中间件 | LI.FI, Fun.xyz, Yield.xyz, DFlow, DoubleZero |
| RWA | Paxos, Ondo, Centrifuge |
| 密码学 | Zama, Fhenix, zkMe |

---

## 使用本 Skill 的方式

分析 crypto 项目时，从 Multicoin 框架出发追问：

1. **这属于八大主题的哪一个？** 如果无法归入 → 可能不是 Multicoin 会投的方向
2. **是否在"可信中立链"上构建？** 企业链/应用链的第三方建设者吸引力存疑
3. **是否利用了区块链的第一性优势？** 全球无许可访问、原子可组合性、实时审计性
4. **RWA 用哪种模型上链？** 不同资产类别天然适配不同模型
5. **Token 是否设计良好？** 不是每个产品都需要 Token，不是每个 Token 都能捕获可持续价值
6. **市场微观结构是否考虑了逆向选择？** 链上交易缺乏 TradFi 的自然分层，需通过 CL/ACE 等机制弥补

---

## 参考链接

- 投资论文：https://multicoin.capital/2026/02/06/multicoin-capitals-investment-thesis/
- Solana 论第五版：https://multicoin.capital/2025/01/22/the-solana-thesis-internet-capital-markets/
- RWA 论：https://multicoin.capital/2026/03/19/rwas-are-just-built-different/
- 逆向选择：https://multicoin.capital/2026/02/17/adverse-selection-rules-everything-around-me/
- ACE 论：https://multicoin.capital/2026/02/10/ace-is-the-place-with-the-helpful-value-capture/
- 互联网劳动力市场：https://multicoin.capital/2026/03/10/internet-labor-markets/
- 2019 Mega Theses：https://multicoin.capital/2019/04/24/multicoin-investment-thesis/
