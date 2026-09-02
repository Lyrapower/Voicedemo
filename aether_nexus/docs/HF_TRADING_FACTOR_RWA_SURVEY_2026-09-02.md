# Trading 信号 / 因子挖掘 / RWA 链上读 · HF 调研 · 回执 · 2026-09-02

> 审:Lyra 问"有关于 trading 信号,因子挖掘,RWA 链上读的模型或项目吗"
> 模式:只读 web 调研,未装任何模型、未改任何文件、未 commit。
> 性质:内部对账回执(架构骨架 + 项目链接 + license + harness 映射 + Mac-fit)。无密钥/身份/store 正文/user 数据。若外发 review 区,按 `receipt-redaction.mdc` 复核(本件已无活体)。

---

## 0. 前提与诚实记账

- 这三类 HF 上**框架/平台多过纯模型 checkpoint**——因子挖掘和 RWA 链上主要是项目(Qlib 生态),HF 上现成可下载的模型 checkpoint 较少(FinGPT-Forecaster 是一个)。
- harness 现状(来自 `app/harness/capability_registry.py` + `alpha-platform/` + `app/crypto_rwa/`):`trading.paper.signal_daily`(aether_paper)、`crypto.rwa.scan_public`、`alpha-platform` 的 `factor_sandbox`/`factory_pipeline`/`factory_prompts`、`app/crypto_rwa/rwa_onchain_reader.py` v5。
- **不装**——装哪个 Lyra 拍(动 capability_registry / 部署形态需授权,见 AGENTS.md R5)。
- Mac(M4):这些多是框架/SDK/标准(Python/API),Mac 都能跑;唯一需 GPU 的是 FinGPT Llama2-7b,可走 cloud API 免 GPU。

---

## 1. Trading 信号(方向/价格预测)

| 项目/模型 | 是什么 | License | harness 映射 | Mac? |
|---|---|---|---|---|
| **[FinGPT-Forecaster](https://huggingface.co/FinGPT/fingpt-forecaster_dow30_llama2-7b_lora)** | HF checkpoint:Llama2-7b LoRA,吃 N 周新闻+财报 → 输出 positive developments / concerns / 下周股价方向预测 | 开源(Llama2 gated) | `trading.paper.signal_daily` 的情绪/新闻信号源 | ⚠️ 7B 需 GPU,可走 cloud API 免 GPU |
| **[FinRobot](https://github.com/ai4finance-foundation/finrobot)** | AI4Finance 多 agent 平台,Market Forecaster Agent + 8 专项 agent,FMP/Finnub 接入,CoT 结构化推理 | 开源 | 比 FinGPT 更全的 agent 框架;harness agents 可参考其多 agent 编排 | ✅ Python |

---

## 2. 因子挖掘(alpha)

| 项目 | 是什么 | License | harness 映射 | Mac? |
|---|---|---|---|---|
| **[QuantaAlpha](https://github.com/QuantaAlpha/QuantaAlpha)** | LLM 驱动进化因子挖掘,轨迹自进化(mutate/crossover),GPT-5.2 下 IC 0.0472,CSI300→CSI500/S&P500 可迁移。**HF 数据集**:`QuantaAlpha/qlib_csi300` | 开源 | 直接对齐 `alpha-platform` 的 `factor_sandbox`/`factory_pipeline`/`factory_prompts` | ✅ Python(LLM 走 cloud) |
| **[FactorEngine](https://arxiv.org/html/2603.16365)** | 程序级因子挖掘,因子=Turing-complete 代码,知识注入(财报→可执行因子程序),LLM 搜索+Bayesian。**因子可执行可审计** | 论文/框架 | 对齐 harness `provenance.py` 的"可审计"诉求;`factory_schema` 可参考 | ✅ |
| **Chain-of-Alpha** | 双链(生成链+优化链),A 股 benchmark,全自动公式化因子挖掘 | 论文 | `factory_prompts` 的双链参考 | ✅ |
| **AlphaBench** | 因子搜索范式 benchmark(CoE/ToT/进化),Qlib 回测 | — | 评测 harness `factor_sandbox` 因子质量 | ✅ |
| **[Qlib (Microsoft)](https://github.com/microsoft/qlib)** | 量化基座,Alpha158 因子集,RL+监督学习,**RD-Agent** 自动 R&D | MIT | `alpha-platform` 的基座候选;Alpha158 可直接用 | ✅ |

---

## 3. RWA 链上读

| 项目/标准 | 是什么 | harness 映射 | Mac? |
|---|---|---|---|
| **[ERC-8004 (Trustless Agents)](https://eips.ethereum.org/EIPS/eip-8004)** | 链上 agent 身份/声誉/**验证**三注册表(MetaMask+EF+Google+Coinbase 2025-08 提)。Validation Registry 支持 stake-secured re-execution / zkML / TEE oracle | **直接补 RWA 缺口 G1/G3**——链上验证注册表 = provenance 的链上层;harness `mark_verified()` 的确定性谓词可上链 | 标准 |
| **[Casper AI Portfolio Agent](https://github.com/thesithunyein/casper-ai-portfolio-agent)** | RWA 组合 agent,x402 微支付,实时 RWA 价(T-bills/PAXG/ONDO),`store_analysis` 上链 + explorer proof | RWA 链上读写参考架构;对齐 `rwa_onchain_reader.py` 的"证据卡 + source_url" | ✅ Rust/Odra |
| **[qdf-sdk](https://pypi.org/project/qdf-sdk/)** | DeFi 池数据 SDK,7000+ 池/60+ 链,APY/TVL/momentum/IL risk 评分,DeFi Llama + 链上直查 | RWA/DeFi 数据接入,走契约 §七 出网工具层(需进 EGRESS.md) | ✅ Python API |
| **Allium** | 链上数据标准化(150+ 链) | RWA reader 的 RPC 数据基础层 | API |

---

## 4. 三个值得注意的点

### 4.1 ERC-8004 是真的存在,且补 RWA 缺口

处决案 4 问"上个月我们讨论过 x402 的 ERC-8004 注册吗",store 答"没有"(对的,没讨论过),但这个标准**实际存在**(2025-08 提,MetaMask/EF/Google/Coinbase)。它的 **Validation Registry**(staker 重跑 / zkML / TEE oracle 验证)正好是 RWA 缺口 **G1(reader 没接 provenance)+ G3(只降不升断言)**的链上解法——harness `mark_verified()` 的确定性谓词可以注册成 ERC-8004 validation,链上可验。这条值得立项。

### 4.2 QuantaAlpha 的 HF 数据集

`QuantaAlpha/qlib_csi300` 有预计算价量 HDF5,`alpha-platform` 的 `factor_sandbox` 可直接拿来跑因子挖掘,不用自己造数据。

### 4.3 Qlib 是共同基座

QuantaAlpha/FactorEngine/Chain-of-Alpha/AlphaBench 全建在 Qlib 上。`alpha-platform` 若要系统性接因子挖掘生态,以 Qlib 为基座最省力(Alpha158 现成,RD-Agent 自动 R&D)。

---

## 5. 与契约/缺口的对齐点

- **ERC-8004 Validation Registry** → RWA 缺口 G1(reader 接 provenance)+ G3(只降不升断言)的链上解法;`mark_verified()` 谓词可上链
- **QuantaAlpha/FactorEngine** → `alpha-platform` `factor_sandbox`/`factory_pipeline` 的因子挖掘增强;FactorEngine 的"因子=可执行代码 + 可审计"对齐 harness provenance
- **FinGPT/FinRobot** → aether `trading.paper.signal_daily` 的新闻/情绪信号源
- **qdf-sdk** → RWA/DeFi 数据接入,走契约 §七 出网工具层(需进 EGRESS.md 登记,见 RWA 缺口 G6)

---

## 6. 自检

- [x] 只读 web 调研,未装任何模型、未改任何文件、未 commit
- [x] 每个 candidate 带链接 + license + harness 映射 + Mac-fit
- [x] 诚实记账:三类多为框架/平台,非纯 HF checkpoint(FinGPT-Forecaster 是少数 checkpoint)
- [x] 未宣称"已装/可用";只列候选供 Lyra 拍
- [x] 范围:trading 信号 / 因子挖掘 / RWA 链上读;未碰 local_gateway.py / 冻结链 / 部署形态

—— 戌,2026-09-02 PDT(只读 web 调研)
