# 后续待办与已知推迟

> 🌐 **语言:** [English](./follow-ups.md) · 中文(当前)

这是在里程碑走查与盲审中浮现的**非阻断**后续待办与已知推迟的滚动清单。它们都不阻断任何里程碑的验收;记在这里是为了不丢失。属于某个里程碑的设计级推迟,留在该里程碑的设计文档里(如 `M7.md` §13);本文件收集跨切面的、验收后的项。

优先级仅供参考:**健壮性** > **UX** > **装饰 / 测试卫生**。

## 待办

### 健壮性 / 一致性

- **A1 —— 各仓库 PATCH null 处理统一化。** 仓库层守卫 `reject_null_on_non_nullable`(`backend/app/repositories/_update_guard.py`)已应用到两个"盲 `setattr` 循环"仓库(`maintenance_schedule`、`shopping_list`),故对 NOT NULL 列发显式 `null` 会返回干净的 **422**。其余七个仓库(`category`、`location`、`item_definition`、`stock_instance`、`note`、`tag`、`attachment`)则**静默忽略**对 NOT NULL 列的显式 `null`(`if x is not None` / `set_*` flag 模式跳过它,返回 **200** 不变)。两种行为在各 PATCH 端点间不一致。后续:做一次一致性 pass,把所有 PATCH 更新都接到同一守卫(或明确决定保留静默忽略并写明)。*来源:`review-notes/patch-null-guard-review.md` MINOR #2。*

- **A2 —— 通知的 subject 实体被删除时的孤儿通知。** 删除**维护计划**现在会经 `NotificationRepository.delete_for_subject`(由 `MaintenanceScheduleService.delete` 调用)清理其通知。同一类孤儿/dedup 碰撞对其他 subject 仍存在:删除**库存实例**或**物品定义**会留下其 `instance` / `best_before` / `warranty` 通知 —— 以及经级联删除的维护计划而来的 `maintenance_schedule` 通知 —— 都未清理。症状:铃铛里残留指向已删 subject 的陈旧条目;且因 SQLite 复用整型主键,重建一个复用旧 id + 相同目标日期的 subject 会被静默判重而压掉。后续:在实例/定义删除路径上调用 `delete_for_subject`(或一个更通用的 subject 清理钩子)。*来源:`review-notes/maint-delete-notif-cleanup-review.md`(范围外说明)。*

### UX

- **B1 —— 购物清单勾选入库:弹窗 → 内联动作。** 勾选一条绑定了定义的购物项会弹出一个 modal 让你输入入库数量/位置。建议改为内联/快捷动作(或预填+确认),而不是用 modal 打断。*来源:走查记录。涉及 `frontend/src/pages/ShoppingList.tsx`(勾选流程)。*

- **B2 —— 维护计划的可发现性。** 维护计划在实例详情页(`/instances/:id`),需从物品详情点进某个具体 lot 才能到。可考虑在物品详情的 lot 行上给个提示(如"含维护"徽标或快捷链接),让该功能更易找到。*涉及 `frontend/src/pages/Items.tsx`(lot 行)与 `frontend/src/pages/InstanceDetail.tsx`。*

- **B3 —— MaintenancePanel 对每个实例都渲染。** 该面板对所有实例(含消耗品)无条件显示,因为没有干净的耐用/kind 信号可用于门控;消耗品 lot 会多出一个空的维护区块(无功能损害)。待有干净信号后将其限定到耐用品。*来源:`review-notes/M7-report.md` §5 #3。涉及 `frontend/src/pages/InstanceDetail.tsx`。*

- **B4 —— LLM base URL 字段无示例/提示。** provider 配置的 **Base URL** 输入框没有 placeholder,因此不明显:该值必须**已经带上版本段**(如 `https://openrouter.ai/api/v1`,而非 `https://openrouter.ai/api`)。M9.1 走查中,这个歧义叠加(已修的)双 `/v1` bug,产生了一个令人困惑的"模型不可用"报错。后续:给 Base URL 字段加 placeholder / 帮助文案(如 `https://openrouter.ai/api/v1`),并可选地在 URL 看起来不带版本段时给个轻量客户端提示。*来源:M9.1 走查。涉及 `frontend/src/pages/Configuration.tsx`(LLM 区块) + `frontend/src/i18n/locales/{en,zh}/llm.json`。*

### 装饰 / i18n

- **C1 —— "今天到期"无独立文案。** 对维护(以及既有 best_before / warranty 模板),`days_remaining === 0` 渲染成"0 days remaining",而非独立的"今天到期"文案。在各提醒模板里加一个独立字符串。*来源:`review-notes/M7-report.md` §5 #5。涉及 `frontend/src/pages/Notifications.tsx` + notifications i18n 目录。*

### 测试卫生

- **D1 —— MaintenanceCard 测试的 React `act()` 警告。** 仪表盘"即将维护"tile 的测试有一处未包进 `act(...)` 的异步状态更新,产生一条非失败警告。把相关更新包进 `act()` / `waitFor`。*来源:`review-notes/M7-report.md` §5 #4。*

## M7 走查期间已解决

为可追溯而记录(均在 `main` 上):

- PWA 陈旧缓存 —— 现在普通刷新即可拿到新构建(`5fc6df3`)。
- 购物清单 —— 已购的 auto 行在其定义再次低库存时被重开(`b422c80`)。
- 消耗(FIFO)—— 数量默认填 1(`6374dd7`)。
- 维护通知 —— 跳转到实例详情页而非错误目标(`cdbe923`)。
- PATCH null 守卫 —— 两个盲循环仓库对非空列的显式 null 返回 422(`b6430a5`);跨仓库一致性 pass 作为 **A1** 仍待办。
- 删除维护计划 —— 连带删除其通知(`60eb95f`)。

## M9.1 走查期间已解决

为可追溯而记录(在 `main` 上):

- LLM chat URL 双 `/v1` —— `chat()` 拼了 `/v1/chat/completions`,而 `list_models()` 用 `/models`,于是一个标准的带版本段 base URL(`…/api/v1`)得到 `…/api/v1/v1/chat/completions` → 404 被误标为"模型不可用"。已修:两个端点都对"已含版本段的 base URL"追加 `/<endpoint>`,并做尾部斜杠归一化(`e6971bb`)。

## 设计层推迟(刻意,非缺陷)

以下刻意不做,在各里程碑设计文档追踪。来自 `docs/plan/milestones/M7_zh.md` §13:按用量计的维护、维护完成历史、按定义的计划、按用户的维护提前期、以及 TickTick 购物清单同步接缝。来自 `docs/plan/milestones/M9.1_zh.md` §13:允许 loopback 的开关(同机 Ollama)、模型自动发现 UI、流式 / 函数调用 / 结构化输出、token 与成本计量 + 预算、重试 / 退避、多 provider / 回退 + 按用户配置、以及密钥静态加密。
