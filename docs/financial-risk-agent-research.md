# 金融风控调查 Agent：项目与可验证数据调研

> 调研日期：2026-09-20  
> 目标：为一个可公开上传 GitHub、可重复验证、适合 RTX 5060 + 本地 vLLM + 外部 API 的金融风控 Agent 选择数据、架构和评测方案。

## 结论

首版不应做泛化的“金融聊天机器人”，也不应让大语言模型直接凭文字判断交易是否欺诈。推荐独立实现一个 **银行开户欺诈告警复核 Agent（Fraud Alert Review Agent）**，使用最新版 **FiFAR** 作为主数据和隐藏真值：

- 输入是一条已经被传统欺诈模型报警的开户申请；
- Agent 查询申请字段、告警模型分数、确定性统计和可解释性证据；
- Agent 可以选择自动给出建议，也可以在容量约束下把案件转给一位“分析员”；
- 系统记录结构化结论、引用的证据 ID、工具调用和转人工选择；
- 离线评测器在 Agent 完成后才读取 `fraud_bool` 与专家预测，核验系统结论。

FiFAR 正好模拟这个场景：它包含约 30K 条被模型报警的开户申请、每条记录的真实标签，以及 50 位合成欺诈分析员对每条记录的判断，并提供不同专家团队和工作容量场景。[Scientific Data 论文](https://www.nature.com/articles/s41597-025-04664-y)；[官方数据页](https://springernature.figshare.com/articles/dataset/Financial_Fraud_Alert_Review_Dataset/28351172)；[官方 OpenL2D 仓库](https://github.com/feedzai/openl2d)。

这比 PaySim 更贴近“告警复核 + 人机协作”，比 IBM AML 数据轻得多，也比 BAF 单独使用多了可验证的人工转交和容量决策。第二阶段如果要做资金网络、洗钱模式和图查询，再增加 IBM AML 数据，而不是把两个任务硬塞进首版。

## 1. 主数据：FiFAR

### 1.1 数据是什么

FiFAR（Financial Fraud Alert Review Dataset）的最新版随 2025 年的 Scientific Data 论文发布。官方描述为：从 BAF 银行开户欺诈数据出发，由告警模型筛出约 30K 个高风险案件，再为这些案件生成 50 位具有不同能力、偏差、特征依赖与容量限制的合成欺诈分析员判断。[论文摘要和数据记录](https://www.nature.com/articles/s41597-025-04664-y)；[Figshare 元数据](https://springernature.figshare.com/articles/dataset/Financial_Fraud_Alert_Review_Dataset/28351172)。

官方数据包含：

- `Base.csv`：BAF Base v1 的 100 万条合成开户申请；
- `BAF_alert_model_score.parquet`：告警模型打分后的部署期申请；
- `alerts.parquet`：超过告警阈值、进入复核流程的约 30K 条案件；
- `expert_predictions.parquet`：50 位合成分析员对每个告警的二元判断；
- `expert_parameters.parquet`：分析员的能力、偏差和特征依赖等参数；
- 专家团队与容量场景，用于评测在有限人工资源下的分配策略。

以上结构由[官方论文 Data Records](https://www.nature.com/articles/s41597-025-04664-y)和[官方 OpenL2D README](https://github.com/feedzai/openl2d)给出。FiFAR 的基础标签为 `fraud_bool`，0 表示正常申请、1 表示欺诈申请；50 位分析员的判断采用同样的二元约定。[官方 Figshare 数据说明](https://springernature.figshare.com/articles/dataset/Financial_Fraud_Alert_Review_Dataset/28351172)。

FiFAR 不是现实银行客户数据：开户申请与分析员判断均为合成数据。其价值是可以完整知道标签并复现实验，而不是证明模型已经能直接用于真实银行。[论文的技术验证与使用说明](https://www.nature.com/articles/s41597-025-04664-y)。

### 1.2 下载、校验和许可证

- 唯一官方发布页：[Springer Nature Figshare](https://springernature.figshare.com/articles/dataset/Financial_Fraud_Alert_Review_Dataset/28351172)
- DOI：[`10.6084/m9.figshare.28351172.v1`](https://doi.org/10.6084/m9.figshare.28351172.v1)
- 文件：`FiFAR.zip`
- 官方大小：209,350,760 bytes
- 官方 MD5：`2255e7b8a391d0ab567f37ec27e52f3d`
- 数据许可证：[`CC BY 4.0`](https://creativecommons.org/licenses/by/4.0/)

本地已下载文件的 MD5 与官方值一致。许可证允许使用、修改和再分发，但要求署名。尽管如此，本项目仍默认 **不把 ZIP、CSV、Parquet 或第三方模型文件提交到 GitHub**；仓库只提供官方下载脚本/说明、固定版本 DOI、哈希校验、数据字典和我们自行生成的小型测试夹具。这既减少仓库体积，也把数据许可证与项目代码许可证清楚分开。

注意：论文页面本身与数据集可能采用不同许可；引用论文文字或图片时不能把数据的 CC BY 4.0 自动套用到论文内容。项目只需要引用论文结论，不复制论文图表或长段文字。

### 1.3 为什么它特别适合 Agent

普通欺诈数据通常只能测“模型分类对不对”。FiFAR 还能测：

1. Agent 是否该自己建议，还是转交人工；
2. 应该转给哪位分析员；
3. 被选分析员在该案件上是否真的判断正确；
4. 当分析员有容量上限时，案件分配是否违反限制；
5. 不同专家团队、负载和时间分布下，策略是否稳定。

FiFAR 论文的核心结论之一是：Learning-to-Defer 方法的排名会随可用专家团队发生明显变化，因此不能只挑一组“最好看”的分析员报告结果。[Scientific Data 技术验证](https://www.nature.com/articles/s41597-025-04664-y)。

## 2. 候选数据比较

| 数据 | 场景与真值 | 规模与可解释性 | 许可证/分发 | 结论 |
|---|---|---|---|---|
| **FiFAR（推荐首版）** | 开户欺诈告警复核；`fraud_bool` 真值；50 位合成分析员判断和容量约束 | 约 30K 告警，基础 BAF 100 万申请；字段是开户、设备、速度、地址、联系方式等业务特征 | 数据 [CC BY 4.0](https://springernature.figshare.com/articles/dataset/Financial_Fraud_Alert_Review_Dataset/28351172)；默认不再分发原始文件 | 最适合验证 Agent 的证据、转人工和资源分配 |
| **BAF** | 银行开户欺诈；每行有真实标签，含时间动态与公平性属性 | 6 个变体，每个 100 万条、30 个特征、跨 8 个月；字段可解释 | Kaggle 数据标记为 CC BY-NC-SA 4.0；官方仓库许可文件为 Apache-2.0 但另有商业使用联系说明。[仓库](https://github.com/feedzai/bank-account-fraud)；[论文](https://arxiv.org/html/2211.13358) | 很好的分类/公平性基准，但没有专家判断和容量；FiFAR 已覆盖所需 Base 数据 |
| **PaySim** | 移动支付欺诈；`isFraud` 和 `isFlaggedFraud` | Kaggle 包约 494 MB；字段直观，但欺诈模式和余额字段有较强模拟痕迹，数据页明确警告不要使用交易后的余额字段作检测 | 数据 [CC BY-SA 4.0](https://www.kaggle.com/datasets/ealaxi/paysim1)；模拟器 [GPL-3.0](https://github.com/EdgarLopezPhD/PaySim) | 适合教学和吞吐测试，不作为可信风控 Agent 的主基准 |
| **AMLSim** | 生成银行转账和 8 类已知洗钱模式；可验证模式子图 | 官方论文对比中的典型规模约 132 万笔；输出账户、交易、报警交易和 SAR 账户等文件 | 代码 [Apache-2.0](https://github.com/IBM/AMLSim) | 可控但运行栈较旧（Java 8、旧版 NetworkX），模拟仅覆盖洗钱分层，首版成本偏高 |
| **IBM AML-Data / AMLworld** | 每笔交易有 `Is Laundering` 标签，另有 8 类模式文件；完整合成真值 | 6 套数据，约 500 万到 1.8 亿笔交易，含账户图、金额、时间、币种和支付类型；官方总包约 41.6 GB | 数据 [CDLA-Sharing-1.0](https://github.com/IBM/AML-Data)；公开再分发需保持协议和署名，[协议条款](https://cdla.dev/sharing-1-0/) | 最适合第二阶段的交易网络/AML 调查；首版对单机开发过重 |
| **SynthAML** | 20K 条 AML 告警及关联交易；标签是历史“上报主管机关/驳回”结果，不是已确认洗钱事实 | 超过 1600 万笔交易；来自丹麦银行真实告警分布的合成数据；字段较少但很适合时序聚合 | 官方 Figshare 的[告警数据](https://springernature.figshare.com/articles/dataset/synthetic_alerts/22396054)与[交易数据](https://springernature.figshare.com/articles/dataset/synthetic_transactions/22396057)均标记为 CC0；[Scientific Data 论文](https://www.nature.com/articles/s41597-023-02569-2) | 真实感强，但标签代表分析员处置而非犯罪真值，不能用来声称 Agent 识别了真实洗钱 |

### 2.1 BAF 的重要限制

BAF 的每个合成数据集有 100 万个申请、30 个特征并跨 8 个月，标签来自原始数据中的 ground-truth 记录；但论文明确要求它只用于评测 ML/Fair ML 方法，不应把其上训练的模型直接用于现实欺诈检测。[BAF 论文的数据说明与限制](https://arxiv.org/html/2211.13358)。

BAF 的推荐时间切分是前 6 个月训练、后 2 个月测试，而不是随机切分；论文在 5% FPR 的固定运营点报告 TPR，并以组间 FPR 比率衡量公平性。[BAF 论文实验设置](https://arxiv.org/html/2211.13358)。FiFAR 已进一步把它变成告警复核问题，因此首版无需再单独下载 BAF v2。

### 2.2 为什么不选 PaySim

PaySim 的官方 Kaggle 页面说明数据由移动支付模拟器生成，欺诈行为集中于攻击者控制账户后转账并提现，同时明确指出被发现的欺诈交易会被取消，因此 `oldbalanceOrg`、`newbalanceOrig`、`oldbalanceDest`、`newbalanceDest` 不应直接用于欺诈检测。[PaySim 官方数据页](https://www.kaggle.com/datasets/ealaxi/paysim1)。这使它非常适合讲解类别不平衡、数据泄漏和时间切分，却不适合作为一个“结论可信”的主项目。

### 2.3 AMLSim 与 IBM AML-Data 的关系

AMLSim 是生成器，目标是产生合成银行交易与已知洗钱模式，并提供脚本把输出验证回参数文件；其代码为 Apache-2.0。[AMLSim 官方仓库](https://github.com/IBM/AMLSim)。

IBM 后续的 AMLworld/AML-Data 更完整：它模拟放置、分层和整合，支持多银行、多币种和更多交易形式；合成真值可以追踪被洗资金经过多跳交易的传播。官方公开 6 套数据，单套约 500 万至 1.8 亿笔交易，并建议按时间做 60/20/20 切分。[IBM 论文](https://arxiv.org/html/2306.16424)；[官方数据仓库](https://github.com/IBM/AML-Data)。它非常适合后续加入图查询、资金环路、fan-in/fan-out、scatter-gather 和 SAR 草稿，但不是当前最短的可验证闭环。

## 3. 可借鉴的官方 GitHub 项目

所有项目只用于理解概念、架构和评测方法。**不复制、改写或拼接其代码、提示词、前端或 IaC**；本项目的代码、提示词、数据适配器与测试均独立实现。

### 3.1 Feedzai OpenL2D

- 仓库：[feedzai/openl2d](https://github.com/feedzai/openl2d)
- 可借鉴思想：告警模型 → 高风险案件 → 人机协作；分析员能力不同；分配受容量限制；跨不同团队评测。
- 许可证：许可证正文是 Apache-2.0，但文件首行另写“商业使用请联系 Feedzai”。[许可证原文](https://raw.githubusercontent.com/feedzai/openl2d/main/LICENSE.txt)
- 处理：不复用源码或配置，只使用官方发布的 FiFAR 数据和论文定义的研究问题；我们自己设计工具接口、Agent 状态机、提示词和评测器。

### 3.2 AWS Fraud Detection and Prevention Agentic Platform

- 仓库：[aws-samples/sample-fraud-detection-and-prevention-fdp-agentic-platform](https://github.com/aws-samples/sample-fraud-detection-and-prevention-fdp-agentic-platform)
- 可借鉴思想：前端、API 服务、工作流和基础设施分层；把欺诈侦测、响应和业务用户界面分开。
- 许可证：MIT-0。[仓库许可证说明](https://github.com/aws-samples/sample-fraud-detection-and-prevention-fdp-agentic-platform)
- 处理：它依赖 AWS、Bedrock、Terraform/Terragrunt，不适合直接搬到本地 5060；只借鉴模块边界。

### 3.3 AWS Agentic Value Accelerator（金融服务）

- 仓库：[aws-samples/sample-agentic-value-accelerator](https://github.com/aws-samples/sample-agentic-value-accelerator)
- 可借鉴思想：欺诈评分、调查、SAR 报告职责分离；人工审批；结构化输出；审计日志；预算、速率限制和可观测性。
- 许可证：Apache-2.0。[官方 README](https://github.com/aws-samples/sample-agentic-value-accelerator)
- 处理：项目体量和 AWS 依赖远超当前需要；只提取“证据先于报告、敏感操作需审批、全程可审计”三个原则，不采用其多 Agent 数量、代码或提示词。

### 3.4 NVIDIA Financial Fraud Detection Blueprint

- 仓库：[NVIDIA-AI-Blueprints/Financial-Fraud-Detection](https://github.com/NVIDIA-AI-Blueprints/Financial-Fraud-Detection)
- 可借鉴思想：把数据准备、模型训练与在线推理解耦；模型输出风险分数和 SHAP 解释，LLM 只组织调查报告。
- 许可证：仓库显示 Apache-2.0，但使用的 NIM/容器另受 NVIDIA 软件与产品条款约束。[官方 README 的 License 与 Terms of Use](https://github.com/NVIDIA-AI-Blueprints/Financial-Fraud-Detection)
- 硬件边界：官方最低要求 32 GB GPU 显存，RTX 5060 8 GB 不适合照搬。[官方硬件要求](https://github.com/NVIDIA-AI-Blueprints/Financial-Fraud-Detection)
- 处理：只借鉴“传统/图模型做数值判断，LLM 负责调查编排和解释”的架构。

### 3.5 IBM Multi-GNN

- 仓库：[IBM/Multi-GNN](https://github.com/IBM/Multi-GNN)
- 可借鉴思想：把交易视为有向多重图，将洗钱识别视为边分类，并使用时间切分与图结构特征。
- 许可证：Apache-2.0。[官方仓库](https://github.com/IBM/Multi-GNN)
- 处理：作为第二阶段 AML 图实验的基线来源；首版不复制其训练代码。

### 3.6 Fraud Detection Handbook

- 仓库：[Fraud-Detection-Handbook/fraud-detection-handbook](https://github.com/Fraud-Detection-Handbook/fraud-detection-handbook)
- 可借鉴思想：时间切分、类别不平衡指标、按每日复核容量评测和可复现实验。
- 许可证：Notebook 代码 GPL-3.0，文字和图片 CC BY-SA 4.0。[官方许可证说明](https://github.com/Fraud-Detection-Handbook/fraud-detection-handbook#license)
- 处理：只采用一般评测思想，不复制其 GPL 代码、文字或图片。

## 4. 推荐的原创落地方案

### 4.1 系统边界

项目名建议：**Fraud Review Copilot**（开户欺诈告警复核与转交 Agent）。

```text
FiFAR 本地数据（标签隔离）
        │
        ▼
确定性工具层 ── 案件查询 / 分位数 / 风险分数 / 特征贡献 / 专家容量
        │
        ▼
Agent 编排层 ── 选择证据工具 / 判断信息是否足够 / 自动建议或转人工
        │
        ├── 本地 vLLM：隐私优先、低成本报告和离线运行
        └── 外部 API：复杂工具规划与高质量报告（可选）
        │
        ▼
结构化案件报告 + 证据 ID + 工具轨迹 + 分配结果
        │
        ▼
离线评测器读取隐藏 fraud_bool / 专家预测并核验
```

Agent 不是欺诈分类器的替代品。数值风险分数、分位数、特征贡献和容量判断必须由确定性 Python/SQL 工具产生；LLM 负责决定查什么、何时停止、是否转人工，以及把工具结果组织成可读报告。

### 4.2 首版工具

1. `get_case(case_id)`：返回允许 Agent 看到的开户申请字段，不返回 `fraud_bool`。
2. `get_alert_score(case_id)`：返回传统告警模型分数和阈值。
3. `compare_with_population(case_id, feature_names)`：返回训练期分位数与同群体基线。
4. `get_feature_contributions(case_id)`：返回由本地分类器/解释器计算的前 N 个正负贡献。
5. `list_available_reviewers(batch_id)`：返回分析员匿名 ID、剩余容量和只基于训练期统计的可靠性画像。
6. `defer_to_reviewer(case_id, reviewer_id)`：消耗容量并返回该分析员在当前案件上的判断；调用前 Agent 看不到该判断。
7. `submit_recommendation(...)`：提交固定 JSON Schema 的结论、置信度、证据引用、是否转人工和理由。

所有工具均为 allowlist；Agent 不能执行任意 SQL、Shell 或 Python。任何未来的“冻结账户、拒绝开户、提交 SAR”等动作只生成建议，必须人工确认，首版不执行现实副作用。

### 4.3 模型分工

- **默认可复现路径**：本地 Qwen3.5-4B INT4 + vLLM，确保没有外部 API 也能完整运行评测。
- **高质量路径**：通过 OpenAI-compatible adapter 接入用户选择的外部强模型，负责工具规划和最终报告。
- **确定性路径**：风险分类、SHAP/特征贡献、统计分位数、容量和指标计算全部在 CPU 上运行；RTX 5060 只承载本地 LLM，不承担大规模 GNN 训练。
- **降级路径**：外部 API 失败时切到本地模型；模型都失败时仍可输出传统模型分数和规则证据，不丢失案件。

不要把 API Key 写入代码、README、日志或提交历史；只从本地环境变量或不入 Git 的 `.env` 读取。

## 5. 如何验证“推理对不对”

### 5.1 不验证隐藏思维链

不要求模型展示或保存内部思维链，也不使用“推理写得像不像”作为评分。只评测可观察产物：

- 调用了哪些工具；
- 工具返回了什么；
- 报告引用了哪些证据 ID；
- 最终结构化判断是什么；
- 是否转人工、转给谁；
- 是否满足容量和安全规则。

这能复现和单元测试，也避免把语言流畅度误当作推理正确性。

### 5.2 标签隔离

运行时至少分成三张逻辑表：

```text
case_features      Agent 可查，不含 fraud_bool
reviewer_runtime   只有成功分配后才返回指定分析员判断
ground_truth       仅 evaluator 可读，含 fraud_bool 和完整专家预测
```

自动测试必须确认：

- Agent 工具的 schema 中没有 `fraud_bool`；
- 提示词、日志和 RAG 文档中没有标签；
- 未调用 `defer_to_reviewer` 前不能访问当前案件的专家判断；
- 测试集统计不得使用未来月份或测试标签计算。

### 5.3 四层评测

**A. 最终风险判断**

- Precision、Recall、F1、PR-AUC；
- 固定 5% FPR 运营点的 TPR，与 BAF/FiFAR 的告警设定一致；
- 混淆矩阵和误报/漏报成本；
- 按月份、年龄组和其他受保护属性分别报告 FPR/TPR，不能只给总体准确率。

FiFAR/BAF 是明显不平衡任务，因此准确率不是主指标。BAF 论文使用 5% FPR 下的 TPR，并用组间 FPR 比率衡量公平性。[官方论文设置](https://arxiv.org/html/2211.13358)。

**B. 转人工与专家分配**

- 自动处理覆盖率；
- 转人工后的系统总体准确率/成本；
- 容量违规次数（目标必须为 0）；
- 选择专家相对“当时可用的最佳专家”的 regret；
- 与四个基线比较：模型全自动、全部转人工、随机可用专家、固定最佳历史专家。

结果必须跨官方不同专家团队和容量场景汇总，至少报告均值、方差和最差场景，不能只展示最好的一组。[FiFAR 技术验证](https://www.nature.com/articles/s41597-025-04664-y)。

**C. 证据忠实度**

- 每个证据 ID 必须能回查到工具输出；
- 报告中的数值必须与工具返回逐项相等；
- 结论不得引用未调用工具或不存在字段；
- 对“最高风险因素”等排序声明，用代码核对其是否真在前 N 个贡献中；
- 对报告做反事实测试：改变无关字段不应显著翻转结论，改变关键风险证据应产生可解释变化。

这些检查用 Python 断言和 JSON Schema 完成，不用另一个 LLM 主观打分作为唯一依据。

**D. 工程指标**

- 每案端到端延迟、模型调用次数、token 与 API 成本；
- 工具失败率、重试次数、超时和降级成功率；
- 本地/外部模型在完全相同案件集上的质量—成本曲线；
- 固定随机种子、模型版本、提示词版本和数据哈希，确保结果可重复。

### 5.4 时间切分与正式测试集

正式结果遵循 FiFAR 的时间顺序和官方场景，测试标签只在 evaluator 内使用。BAF 原论文同样强调用前期月份训练、后期月份测试，以模拟欺诈分布变化。[BAF 时间切分说明](https://arxiv.org/html/2211.13358)。

开发阶段可使用我们自己生成的 schema-compatible fixture；它只能验证工具与工作流，不计入模型质量。最终结论必须来自官方 FiFAR 留出集，且报告数据版本和 MD5。

## 6. 公开 GitHub 的许可证与数据治理清单

### 必须提交

- 我们独立编写的源代码、提示词、JSON Schema 和测试；
- `README.md` 中的官方数据下载步骤；
- `THIRD_PARTY_DATA.md`：数据名称、作者、DOI、来源、许可证、引用格式；
- 下载后哈希校验脚本与预期 MD5；
- `.env.example`，只列变量名，不含 Key；
- `.gitignore`，排除原始数据、模型、缓存、日志和真实 `.env`；
- 自行生成且不来自 FiFAR 行拷贝的小型 fixture；
- 聚合指标、图表和可复现命令，并注明由 FiFAR 计算。

### 默认不提交

- `FiFAR.zip`、`Base.csv`、所有第三方 Parquet；
- OpenL2D/BAF/AWS/NVIDIA/IBM 仓库的代码或提示词；
- 第三方预训练模型文件；
- API Key、请求头、原始 API 日志；
- 能反推出单条源数据的大段报告样本。

### 推荐许可证

由于项目代码和提示词均独立实现，可以为我们自己的代码选择 MIT 或 Apache-2.0。数据不纳入项目代码许可证；`THIRD_PARTY_DATA.md` 单独声明 FiFAR 的 CC BY 4.0，并明确用户从官方地址自行下载。

若未来发布从 FiFAR 派生、包含非微量原始信息的数据文件，应再次检查 CC BY 4.0 的署名要求；若加入 BAF v2、PaySim 或 IBM AML 数据，还必须分别遵守 CC BY-NC-SA、CC BY-SA 或 CDLA-Sharing 的附加要求。这里是工程合规建议，不替代法律意见。

## 7. 分阶段实施建议

### 阶段 A：可验证最小闭环

- 数据加载与标签隔离；
- 传统模型/官方 `model_score` 基线；
- 4 个只读证据工具；
- Agent 输出固定 JSON；
- 与 `fraud_bool` 自动对照；
- 本地 vLLM 与一个外部 API 在同一小型测试集对比。

### 阶段 B：人机协作

- 加入 50 位分析员预测；
- 加入容量状态、转人工工具和分配策略；
- 跑官方团队/容量场景；
- 比较模型全自动、随机分配、规则分配与 Agent 分配。

### 阶段 C：可信报告与产品化

- 特征贡献、证据引用和忠实度断言；
- 人工审批界面与案件审计轨迹；
- Docker 化和一键评测；
- 完成模型卡、数据卡与限制声明。

### 阶段 D：AML 图调查扩展（可选）

- 使用 IBM AML-Data Small；
- DuckDB/图工具查询多跳资金关系；
- 识别 cycle、fan-in/out、scatter-gather 等模式；
- 用 `Is Laundering` 和模式文件核验交易与模式结论。

这一阶段才真正进入“资金流调查”。不要在 FiFAR 项目中声称已经验证洗钱环路或 SAR 事实，因为 FiFAR 是开户欺诈告警复核数据。

## 8. 最终选择理由

选择 FiFAR，不是因为它的数据最大，而是因为它第一次让 Agent 的核心行为都可被独立核验：

- 风险判断有隐藏标签；
- 转人工是否有价值有反事实答案；
- 选择哪位专家有完整预测表；
- 容量是否违规可以确定性检查；
- 时间漂移、群体公平性和成本都能量化；
- 数据只有约 200 MB 压缩包，适合当前电脑；
- 本地 4B 量化模型和外部强模型可以在同一协议下公平比较。

因此首版的目标不是“做出一个看起来很聪明的聊天网页”，而是做出一个 **结论能被标签验证、证据能被工具回查、转交决策能被容量与专家结果验证** 的金融风控 Agent。
