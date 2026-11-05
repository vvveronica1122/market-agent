# 已知问题清单

还没修的问题都记在这里，以后一起挑着改。每条写明：是什么、在哪发现、大致怎么修、要不要付费评估。修好一条就从这里删掉，并在 [LOG.md](LOG.md) 里记一笔。

最后更新：2026-11-05。

## A. AI 写的文字（首页 brief、个股分析、Discover）

| # | 问题 | 在哪发现 | 修的方向 | 付费评估 |
|---|---|---|---|---|
| A1 | brief 把新评分的 "1.6x usual"（平时波动的 1.6 倍）读成成交量："on nearly twice their typical volume"。倍数检查的改写还把正确的 "1.6x its usual pace" 改成了 "volume 60% above usual" | [新闻句检查记录](../evals/tuning/batch2-news-check-2026-11.md)，"Found on the way" 一节 | 给 brief 的数据里把这项写清楚，比如 "-16.8%，平时一天大约动 3.8%"，不用倍数 | 要，改了 brief 的输入 |
| A2 | 倍数检查漏掉 "six times harder"、"three to five times harder" 这类说法 | 同上 | `guards.py` 的倍数规则补上，加离线测试 | 改规则本身不用；最好顺带重跑一次倍数评估 |
| A3 | 因果说法："AMZN jumped 6.4% following its earnings report"（线上首页 brief）；Discover 的 "strong Q3 results, driving their shares higher" 和 "likely driven by its AI-powered advertising platform"（数据里没有这个理由）；VRT 分析里的 "appears linked to the broader sector rotation" | 11 月初的线上 brief；11-05 demo 快照 | brief 和 Discover 的提示词，或者补一条因果检查 | 要 |
| A4 | 已经过去的财报日期：Yahoo 的"下一次财报日期"没更新时，传给 brief 的天数是负的（-3、-7、-8），brief 写出"三天前刚发过财报"，但没有可靠来源支撑 | 线上 brief；11-05 的前向记录里有 4 家 | 天数为负时不当作"下一次"，改传上一次财报日期 | 要 |
| A5 | 给没有发布时间的新闻标上时间："reported this morning"、"A headline this morning"。数据里根本没有新闻时间，而 brief 提示词自己的示例就写着 "reported this morning" | [评估场景记录](../evals/tuning/scenarios-2026-11.md)；新闻句检查记录 | 改提示词里的示例；或者把新闻时间传进去 | 要 |
| A6 | 日历范围和计数算错：把 12 天后的 NVDA 算进"未来一周"；"the only name reporting within the week" 说的是 9 天后的财报；说 1 月 26 到 28 日有"六家"发财报，其实是七家；说"下一批在 1 月下旬"，漏掉了之前的 AVGO、MU、TSM | 11-05 demo 快照（两次构建）；新闻句检查记录 | 在数据里直接给出"本周内"的名单，不让模型自己判断 | 要 |
| A7 | 比较说错：说 AAPL "跑赢的幅度差不多"，实际 AAPL 是 +1.6 个点，TSLA 是 -7.2 个点 | 11-05 demo 快照 | 先观察会不会反复出现；可以考虑加一条检查 | 先观察 |
| A8 | 某家公司的新闻没加载出来时，约 8% 的 brief 仍会说它（或它所在的一组）"没有新闻"（6/72）。模型检查器能把这个比例降到约 2%，但误报太多、改写会伤到正确内容，所以没合并 | [新闻句检查记录](../evals/tuning/batch2-news-check-2026-11.md) | 检查器只处理点名这家公司、或说到包含它的一组的句子；只删被标的那一句，不整篇重写 | 要，先写计划 |
| A9 | 日期未知时，"the calendar is quiet until CRM in 18 days" 这种没写 "known" 的说法，两道检查都没拦住 | 新闻句检查记录 | 补日历规则 | 要 |

## B. 数据

| # | 问题 | 在哪发现 | 修的方向 | 付费评估 |
|---|---|---|---|---|
| B1 | 很多行显示的"头条"其实是别家公司的新闻（AAPL 那行显示 dYdX，NVDA 那行显示 Sandisk），来自 Yahoo 搜索兜底。新旧 demo 都有 | 新旧 demo 对比 | 只保留标题里提到这家公司或代码的结果 | 要，brief 的输入会变 |
| B2 | 只有三家公司的主题里，一家大涨或大跌会让另外两家被标成"个股走势"（leave-one-out 中位数只剩两家可比） | [评估场景记录](../evals/tuning/scenarios-2026-11.md) | 同行太少时不下"个股走势"的结论，或者标明"同行太少" | 可能要 |
| B3 | 个股页取主题数据失败时，会被当成"不在任何主题里"，分析不知道比较数据其实失败了 | 评估场景记录 | 失败时记一个 `theme_error`，像新闻、日历那样告诉模型 | 要 |
| B4 | Discover 的模型回答前面多一句话再接 JSON 时，整个主题列表为空，而且不记日志 | 评估场景记录 | 从第一个 `[` 开始解析；失败时记日志 | 不用 |
| B5 | 低波动的股票（比如 ETN）普通的涨跌，在新评分里也可能得高分 | [关注度记录](../validation/attention-2026-11.md) | 先看前向记录的结果再说 | 不用 |

## C. 评估本身

| # | 问题 | 在哪发现 | 修的方向 | 费用 |
|---|---|---|---|---|
| C1 | 9 个新的留出场景还没付费跑过 | [评估场景记录](../evals/tuning/scenarios-2026-11.md) | 按记录里的计划跑一次，作为基线 | 约 $4–4.50 |
| C2 | 换成新评分以后，brief 场景的输入变了，但还没跑回归评估 | [关注度记录](../validation/attention-2026-11.md)；新闻句检查记录 | 跑一轮现有 brief 场景，重点看 A1 | 约 $3 |
| C3 | judge（评分模型）这次漏掉了全部 9 个读法失败，又错判了 10 个正确的；而且生成和评分用的是同一个模型 | 新闻句检查记录；外部评审第 7 节 | 人工核对一批样本，统计 judge 的误报和漏报 | 主要是人工 |
| C4 | 前向记录要满 20 个交易日才出第一次结果 | [关注度记录](../validation/attention-2026-11.md) | 每个交易日收盘后运行（自动运行与否待你决定） | 免费 |

## D. 外部评审里还没做的

| # | 内容 | 出处 |
|---|---|---|
| D1 | 找 3–5 位目标用户做任务测试：用同一批数据找出该关注的公司，记录用时、遗漏和误判 | [外部评审](MarketAgent_Review_and_Improvement_Plan.md) 第 8 节 |
| D2 | 记录每次调用的延迟、调用次数、token 和费用，模型或提示词改了以后能比较 | 外部评审第 7 节 |
| D3 | 逐步拆分 `web/app.py`（数据组装、评分、模型调用、路由）和前端的大块功能 | 外部评审第 9 节 |
| D4 | 一页结果说明：发现了什么问题、怎么改的、指标怎么变、还剩哪些限制 | 外部评审第 10 节 |
