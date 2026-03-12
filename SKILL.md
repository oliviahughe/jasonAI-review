---
name: jason-kb
description: >
  Jason 财经知识库的完整操作技能。当用户提到以下任何场景时，必须使用本 skill：
  1. 入库/爬取文章：用户发来 URL 要求入库、说"Jason 发新文章了"、"入库这篇"、"批量入库"、"爬取这个链接"
  2. 理财建议：用户问投资配置问题，如"闲钱怎么配"、"该不该买基金"、"A股仓位要调吗"、"现在适合加仓吗"
  3. 财务档案：用户说"我的仓位变了"、"更新我的资产"、"看看我的财务状态"
  4. 知识库查询：用户问"Jason 怎么看 XXX"、"知识库里有没有关于 XXX 的内容"
  5. 建议历史：用户问"之前给我的建议是什么"、"看看历史建议"
  即使用户没有明确说"知识库"或"MCP"，只要涉及 Jason 不跪的内容、个人理财建议、文章入库，都应触发本 skill。
---

# Jason 财经知识库操作指南

你正在操作一个基于财经博主「Jason 不跪」内容构建的私有知识库系统。系统通过 MCP Server（名为 `jason-kb`）提供 9 个工具。数据实际存储位置取决于当前 MCP Server 部署位置：如果客户端连的是本地服务，就写入本机；如果客户端连的是远程服务，就写入远程服务器磁盘。当前 Codex 环境若已在 `~/.codex/config.toml` 中把 `jason-kb` 指到远程 URL，则所有入库、检索、档案读写都命中远程服务。

## 核心原则

1. **给建议时必须检索知识库** — 不要凭空回答理财问题，先调用 `search_knowledge_base` 获取 Jason 的观点作为依据
2. **给建议时必须补充市场信息（默认优先更早窗口）** — 调用知识库的同时，用 Bash 运行 `/last30days` 脚本获取近 30 天信息；默认使用完整 30 天窗口，不追求“当天热点优先”
3. **结合用户财务状况** — 给建议前调用 `get_financial_profile` 了解用户的资产、收入和风险偏好
4. **建议要留痕** — 每次给出实质性理财建议后，调用 `save_advice` 记录
5. **保持连贯性** — 给建议前可调用 `get_advice_history` 查看之前给过什么建议，避免自相矛盾

## 场景判断与工具调用

### 场景 A：用户发来文章 URL 要求入库

用户可能说："入库这篇 https://xxx"、"Jason 今天发了新文章 xxx"、"爬取这个链接"

**执行流程：**
1. 调用 `trigger_crawl(url, source)` — source 根据 URL 判断，微信公众号填"公众号"，知识星球填"知识星球"，拿不准就问用户
2. 报告入库结果（标题、切片数量）
3. 如果爬取失败（反爬、正文为空），告诉用户可以手动复制文章内容保存为 .md 文件放入 raw/ 目录，然后调用 `ingest_article` 入库

### 场景 B：用户要求批量入库

用户可能说："把文章都入库"、"批量入库"、"raw 目录下的文章处理一下"

**执行流程：**
1. 调用 `ingest_all_raw()`
2. 报告汇总结果（新入库 X 篇，跳过 X 篇，失败 X 篇）

### 场景 C：用户问理财/投资问题

用户可能说："我多了 5 万闲钱怎么配"、"现在该买基金吗"、"A 股还能加仓吗"

**执行流程：**
1. 先判断模式：
   - `research`：常识问答、观点咨询、原理解释、方向讨论
   - `advice`：资产配置、买卖建议、调仓、分批计划、持仓风险
   - 若只是查询过去建议，转到场景 F
   - 若只是更新资产/收入/持仓，转到场景 D

2. **并行**执行以下步骤（按模式取用，不要顺序等待）：
   - 调用 `search_knowledge_base(用户问题相关关键词)` 检索 Jason 观点
   - 用 Bash 运行市场信息脚本（见下方命令），获取近 30 天市场动态
   - 如宿主 AI 具备 web search 能力，补充 1 到 3 条高相关结果
   - 只有 `advice` 模式才调用 `get_financial_profile()` 读取财务状态

   **市场信息脚本命令**（根据用户问题替换关键词；默认优先更早窗口）：
   ```bash
   python "C:/Users/69050/.claude/skills/last30days/scripts/last30days.py" "keyword1 keyword2" --quick --days 30 --sources web --emit=compact 2>&1
   ```
   日期策略：
   - 默认：使用完整 30 天窗口，优先引用时间更早且仍相关的信息（非“当天优先”）
   - 仅当用户明确要求“最新/今天/实时”时，才改用更短窗口（如 `--days 3`）
   - 引用时必须带具体日期（YYYY-MM-DD）
   关键词提取规则：**关键词必须翻译为英文**，英文搜索质量远高于中文（Brave 搜索对英文更友好）。对照表：
   - 问恒生科技 → `"Hang Seng Tech Index Hong Kong"`
   - 问 A 股 / 大盘 → `"A-share China stock market CSI"`
   - 问白酒 → `"China baijiu liquor stocks"`
   - 问黄金 → `"gold precious metals"`
   - 问宽基指数 → `"CSI 300 index fund China"`
   - 问原油 → `"crude oil energy stocks"`
   - 问纳斯达克 / 美股 → `"Nasdaq US tech stocks"`
   - 问半导体 / 芯片 → `"semiconductor chips China stocks"`
   - 问卫星通信 → `"satellite communication stocks China"`
   - 其他话题：直接翻译为对应英文金融术语

3. 只有 `advice` 模式才可选调用 `get_advice_history()`，并且只保留最近仍有约束力的建议主线，不要把全部历史原文无限带入

4. 优先使用结构化构建脚本生成临时输入文件：
   路径：`C:/Users/69050/.claude/skills/jason-kb/temp_input.json`

   `research` 模式示例：
   ```bash
   python "C:/Users/69050/.claude/skills/jason-kb/scripts/build_temp_input.py" \
     --question-file "<question.txt>" \
     --kb-file "<kb.txt>" \
     --financial-profile-file "<profile.txt>" \
     --market-data-file "<market.txt>" \
     --web-results-file "<web.txt>" \
     --mode research \
     --as-of-date "YYYY-MM-DD"
   ```

   `advice` 模式且用户提供的是持仓 CSV / 表格时，不要手工拼 `raw_facts`，优先调用：
   ```bash
   python "C:/Users/69050/.claude/skills/jason-kb/scripts/build_temp_input.py" \
     --question-file "<question.txt>" \
     --kb-file "<kb.txt>" \
     --financial-profile-file "<profile.txt>" \
     --market-data-file "<market.txt>" \
     --web-results-file "<web.txt>" \
     --history-file "<history.txt>" \
     --csv-path "<holding.csv>" \
     --mode advice \
     --as-of-date "YYYY-MM-DD"
   ```
   说明：
   - `question.txt / kb.txt / profile.txt / market.txt / web.txt / history.txt` 由宿主 AI 先写成 UTF-8 文本文件
   - `research` 模式只组装轻量问答上下文，不强制要求持仓事实
   - `advice` 模式才会自动解析 CSV、提取 `cash/fund_total/positions/pending_trades` 并写入 `temp_input.json`
   - `现金及活期` 默认会尝试从 `financial_profile` 文本中自动提取；若解析失败，再补 `--cash-cny`
   - 默认焦点资产为 `恒生科技`；若用户问题针对别的资产，可传 `--focus-asset-name` 和 `--focus-keywords`
   - 如无显式止损线，不要传 `--stop-loss-rule-exists`，保持默认 `false`
   - 脚本会自动做一层弹性上下文收敛；`advice` 会保留更多当前事实，`research` 更轻

5. 若没有可用 CSV，才退回手工写 `temp_input.json`

   JSON 结构（`mode`、`web_results` 为新增字段；`raw_facts` 与 `policy_constraints` 只建议在 `advice` 模式携带）：
   ```json
   {
     "mode": "research 或 advice",
     "question": "用户的原始问题",
     "kb_results": "search_knowledge_base 返回的完整内容",
     "financial_profile": "get_financial_profile 返回的完整内容",
     "market_data": "last30days 脚本输出（若执行失败填空字符串）",
     "web_results": "补充 web 搜索结果（若无则填空字符串）",
     "history": "get_advice_history 返回的内容（若未调用填空字符串）",
      "raw_facts": {
        "as_of_date": "2026-03-06",
       "focus_asset_name": "恒生科技",
       "cash_cny": 76531,
       "fund_total_cny": 23366.35,
       "positions": [
         {
           "name": "天弘恒生科技 ETF 联接 (QDII) C",
           "amount_cny": 11253.7,
           "hold_return": "-19.88%"
         }
       ],
       "pending_trades": [
         {
           "date": "2026-03-05",
           "direction": "卖出",
           "asset": "卫星通信",
           "status": "预计到账"
         }
       ]
     },
     "policy_constraints": {
       "single_asset_limit_ratio": 0.15,
       "focus_asset_keywords": ["恒生科技", "Hang Seng Tech"],
       "stop_loss_rule_exists": false
     }
   }
   ```

   结构化字段使用规则：
   - `cash_cny` 与 `fund_total_cny` 用于计算“总金融资产口径”的单资产上限
   - `positions[].amount_cny` 传当前持仓金额，`hold_return` 可传当前持有收益率
   - `focus_asset_name + focus_asset_keywords` 用于锁定重点资产，避免模型把“基金内部占比”和“总金融资产占比”混淆
   - 如果**没有显式止损线**，务必写 `stop_loss_rule_exists=false`，防止模型自行脑补“触及纪律线/止损线”
   - 若某条旧规则已经完成，应在 `question` 或 `history` 中明确写“已完成，不再作为当前动作依据”
   - `research` 模式不要为了凑结构而硬塞 `raw_facts`，否则会把普通咨询错误升级成仓位建议

6. 用 Bash 调用 DeepSeek API 脚本生成建议：
   ```bash
   python "C:/Users/69050/.claude/skills/jason-kb/scripts/call_deepseek.py" 2>&1
   ```
   脚本会自动读取 `temp_input.json`，调用 DeepSeek API，将建议输出到 stdout。
   当前脚本已支持：
   - `research / advice` 分模式 prompt
   - 结构化事实优先（仅 `advice`）
   - “15%上限/止损线”等硬冲突校验（仅 `advice`）
   - 冲突后自动重试（仅 `advice`）
   - 多次失败后拒绝返回错误建议（仅 `advice`）

7. 将脚本输出的建议**原样展示**给用户，不要二次改写或精简

8. 只有 `advice` 模式才调用 `save_advice(建议摘要)` 记录本次建议（摘要由你提炼，不超过 200 字）

**脚本报错处理：**
- 报错「未找到 DeepSeek API Key」→ 提醒用户配置 `C:/Users/69050/.claude/skills/jason-kb/config.json`（见注意事项）
- 报错「缺少 openai 库」→ 提醒用户运行 `pip install openai`
- 其他 API 错误 → 将错误信息展示给用户，询问是否改用本地判断兜底

### 场景 D：用户更新财务信息

用户可能说："我 A 股加仓到 20 万了"、"这个月收入涨到 2 万"、"我把基金卖了"

**执行流程：**
1. 调用 `update_financial_profile(field, value)` — field 用点号分隔，如 "资产.A股"、"月现金流.税后收入"
2. 确认更新结果
3. 如果是重大仓位变动，主动调用 `search_knowledge_base` 检索相关观点，给出简短提示

### 场景 E：用户查询知识库状态

用户可能说："最近入库了哪些文章"、"知识库里有多少文章"

**执行流程：**
1. 调用 `get_recent_articles(n)` 返回文章列表

### 场景 F：用户查看历史建议

用户可能说："之前给我的建议是什么"、"回顾一下历史建议"

**执行流程：**
1. 调用 `get_advice_history(n)` 返回历史建议

## 可用工具速查

| 工具 | 参数 | 用途 |
|------|------|------|
| `search_knowledge_base` | query, top_k=5 | 向量检索知识库 |
| `get_financial_profile` | 无 | 读取用户财务档案 |
| `update_financial_profile` | field, value | 更新财务档案指定字段 |
| `ingest_article` | file_path | 单篇文章入库 |
| `ingest_all_raw` | 无 | 批量入库 raw 目录 |
| `trigger_crawl` | url, source | 爬取 URL 并入库 |
| `get_recent_articles` | n=10 | 查看最近入库文章 |
| `get_advice_history` | n=5 | 查看历史建议 |
| `save_advice` | advice | 保存本次建议 |

## 注意事项

- 数据落点取决于当前连接的 MCP 服务：本地连接写本机，远程连接写远程服务器；Embedding/API 调用是否出机仍取决于该服务端配置
- 如果工具调用报错提示 API Key 无效，提醒用户检查 `config/settings.yaml` 中的配置
- 如果知识库为空（没有文章），引导用户先往 raw/ 目录放入文章并执行入库
- 普通咨询默认应优先走 `research`，不要强行附带持仓和历史建议
- 建议历史只保留最近仍相关的主线摘要，不要无限累积全文

## DeepSeek API 配置（首次使用建议部分必须配置）

在 `C:/Users/69050/.claude/skills/jason-kb/config.json` 中写入以下内容：

```json
{
    "deepseek_api_key": "sk-xxx",
    "deepseek_base_url": "https://your-relay.example.com/v1",
    "deepseek_model": "deepseek-chat"
}
```

| 字段 | 说明 | 是否必填 |
|------|------|---------|
| `deepseek_api_key` | API Key（中转站提供的 key） | 必填 |
| `deepseek_base_url` | 中转站地址（结尾加 `/v1`） | 必填（官方才用默认值） |
| `deepseek_model` | 模型名称（中转站支持的模型） | 选填，默认 `deepseek-chat` |

环境变量 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` 优先级高于 config.json。
