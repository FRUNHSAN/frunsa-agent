"""Frunsa-Agent 安全演示平台 — Streamlit 入口.

Four tabs:
  Tab 1: 引擎 Pipeline — Planning → Orchestration → Critic 全链路实时运行
  Tab 2: Guardrail 安全扫描 — 16 条 AST 规则 + 多种违规注入
  Tab 3: Trace 审计日志 — SQLite 查询 + 时间线可视化
  Tab 4: 架构文档 — 大白话解释 + 案例 + Q&A
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_PARENT = Path(__file__).resolve().parent.parent
_DEMO = Path(__file__).resolve().parent
for p in (str(_PARENT), str(_DEMO)):
    if p not in sys.path:
        sys.path.insert(0, p)

import streamlit as st

# ── Page config ──────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Frunsa-Agent 安全演示",
    page_icon="🛡",
    layout="wide",
    initial_sidebar_state="expanded",
)

DB_PATH = str(_DEMO / "demo_trace.db")

# ── Session state ────────────────────────────────────────────────────────

if "scan_results" not in st.session_state:
    st.session_state.scan_results = None
if "active_violation_ids" not in st.session_state:
    st.session_state.active_violation_ids = set()
if "last_pipeline_items" not in st.session_state:
    st.session_state.last_pipeline_items = []

# ── Helpers ──────────────────────────────────────────────────────────────

def _render_trace_badges(trace_context: dict) -> str:
    """Render ALL trace_context entries as colored HTML badges."""
    if not trace_context:
        return ""
    priority_order = [
        "planning.step_index", "planning.reasoning_depth",
        "planning.parent_step_id", "planning.cumulative_tokens",
        "orchestration.dag_node_id", "orchestration.parallel_depth",
        "orchestration.merge_ordinal", "orchestration.branch_taken",
        "orchestration.retry_count", "orchestration.resource_pool_key",
        "retrieval.chunk_id", "retrieval.latency_ms",
        "critic.score", "critic.verdict",
        "agent.identity",
    ]
    all_keys = list(trace_context.keys())
    ordered = [k for k in priority_order if k in all_keys]
    remaining = sorted(k for k in all_keys if k not in priority_order)
    ordered.extend(remaining)

    badges = []
    for k in ordered:
        v = trace_context[k]
        if isinstance(v, dict):
            v = v.get("id", v.get("role", str(v)[:30]))
        else:
            v = str(v)[:40]
        if k.startswith("orchestration"):
            color = "#3b82f6"
        elif k.startswith("critic"):
            color = "#f59e0b"
        elif k.startswith("planning"):
            color = "#10b981"
        elif k.startswith("retrieval"):
            color = "#ef4444"
        elif k.startswith("agent"):
            color = "#8b5cf6"
        else:
            color = "#6b7280"
        badges.append(
            f'<span style="background:{color}1a;color:{color};'
            f'border:1px solid {color}40;border-radius:4px;'
            f'padding:1px 6px;margin:1px;font-size:0.75em;'
            f'white-space:nowrap">{k}={v}</span>'
        )
    return " ".join(badges)


def _verdict_badge(verdict: str) -> str:
    if verdict == "accept":
        return "✅ accept"
    elif verdict == "rework":
        return "🔄 rework"
    elif verdict == "reject":
        return "❌ reject"
    return verdict


# ── Sidebar ──────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🛡 Frunsa-Agent")
    st.caption("安全感知的 AI Agent 基础设施")
    st.divider()

    st.markdown("### 关键数字")
    st.markdown("""
    | 指标 | 数值 |
    |------|------|
    | 引擎 | 6 (3 stub + 3 LLM) |
    | Guardrail | 16 条 AST 规则 |
    | Trace Key | 18 个 |
    | 测试 | 673 (零失败) |
    | 安全层 | 3 层可验证 |
    """)

    st.divider()
    st.markdown("### 演示控制")

    use_mock = st.checkbox("Mock 模式（无需 API Key）", value=True)

    if st.button("🗑 清空 Trace 数据"):
        from demo_trace import clear_traces
        clear_traces(DB_PATH)
        st.session_state.last_pipeline_items = []
        st.success("已清空")

    st.divider()
    st.caption("面试展示版本 | FRUNHSAN")


# ── Title ────────────────────────────────────────────────────────────────

st.title("Frunsa-Agent 安全演示平台")
st.caption("三层可验证安全机制 + 多引擎 LLM 架构 — 实时演示")

tab1, tab2, tab3, tab4 = st.tabs([
    "🧠 引擎 Pipeline",
    "🛡 Guardrail 安全扫描",
    "📋 Trace 审计日志",
    "📖 架构文档",
])

# ═══════════════════════════════════════════════════════════════════════════
# Tab 1: Engine Pipeline
# ═══════════════════════════════════════════════════════════════════════════

with tab1:
    st.markdown("### Planning → Orchestration → Critic 全链路运行")

    # ── Pipeline architecture overview ──
    with st.expander("📐 引擎流水线架构说明", expanded=False):
        st.markdown("""
        #### 数据流拓扑

        ```
                         ┌──────────────────────┐
                         │    Planning Engine    │
                         │  "目标拆解 → 步骤规划" │
                         └──────────┬───────────┘
                                    │ PlanningContext{goal, sub_tasks, max_parallel_branches}
                                    ▼
                         ┌──────────────────────┐
                         │ Orchestration Engine  │
                         │ "DAG 并行分发 → 结果归并"│
                         │  fan-out=2, pool=cpu │
                         └──────────┬───────────┘
                                    │ 5 × StreamItem (chunk c001..c005)
                                    │ each carrying 6 orchestration.* keys
                                    ▼
                         ┌──────────────────────┐
                         │  Synthesis (Planning) │
                         │ "合并 2 条并行分支输出"  │
                         └──────────┬───────────┘
                                    │ concatenated plan_output
                                    ▼
                         ┌──────────────────────┐
                         │    Critic Engine      │
                         │ "评估 → 打分 → 判定"    │
                         │  score + verdict      │
                         └──────────────────────┘
        ```

        #### 关键设计决策

        | 设计要素 | 实现方式 | 约束来源 |
        |---------|---------|---------|
        | **Protocol 统一签名** | `async fn(context, deadline, pace) → AsyncIterator[StreamItem]` | Phase 1 三层平台宪法 |
        | **引擎间 DI (依赖注入)** | Planning 通过 `orch_factory` 持有 Orchestration，而非硬编码 import | Phase 3 Adapter Pattern |
        | **流式传输** | 每个引擎返回 AsyncGenerator，逐条产出 StreamItem，不做批量缓冲 | Phase 2 Skip Propagation |
        | **Trace 穿透** | 每条 StreamItem 携带 `trace_context` Dict[str, Any]，引擎透明传递不解析 | Phase 9.1 Opaque Context |
        | **Mock ↔ LLM 切换** | 一行 lambda 替换 `orch_factory`，Protocol 保证调用方零改动 | Phase 6 Stub Contract |

        #### 执行阶段

        1. **Decompose (Planning #0-#1)**：解析目标 → 拆解为 2 条 sub-tasks，生成 `planning.{step_index, reasoning_depth, parent_step_id, cumulative_tokens}`
        2. **Dispatch (Orchestration #2-#6)**：fan-out 到两个并行分支 (fast_path / full_rerank)，每条产出一个 chunk，携带完整的 6 个 `orchestration.*` trace key
        3. **Synthesize (Planning #7)**：将 2 条分支的 5 个 chunk 合并为 1 份 `plan_output`
        4. **Evaluate (Critic #0-#2)**：对 plan_output 进行三分项评估 (decomposition / dispatch / synthesis)，各自产出 `critic.{score, verdict}`

        #### 时序特征

        整个 pipeline 是 **确定性 Mock 驱动**（非 LLM）——所有 11 个 StreamItem 在 0.1–0.2 秒内产出。切换到 LLM 引擎后，Planning 和 Critic 阶段将有秒级延迟，Orchestration 阶段保持毫秒级（纯路由，不调 LLM）。
        """)

    goal = st.text_input(
        "输入目标",
        value="构建一个代码安全审计 Agent",
        placeholder="描述你想要 AI Agent 完成的任务...",
    )

    col_run, col_info = st.columns([1, 4])
    with col_run:
        run_btn = st.button("▶ 运行 Pipeline", type="primary", use_container_width=True)

    if run_btn and goal.strip():
        from demo_engine import run_engine_pipeline

        st.info(f"**当前任务**: {goal.strip()}")
        plan_status = st.status("🧠 Planning Engine: 等待启动...", state="running")

        items_log = []
        planning_count = 0
        orch_count = 0
        critic_count = 0
        pipeline_stats = {}

        for item in run_engine_pipeline(goal.strip(), use_mock=use_mock, db_path=DB_PATH):
            if item.get("item_type") == "stats":
                pipeline_stats = item["stats"]
                plan_status.update(label="✅ Pipeline 完成", state="complete", expanded=False)
                break

            items_log.append(item)
            engine = item.get("engine", "")
            ctx = item.get("trace_context", {})
            is_orch = any(k.startswith("orchestration.") for k in ctx)

            if is_orch or engine == "orchestration":
                orch_count += 1
            elif engine == "planning":
                planning_count += 1
            elif engine == "critic":
                critic_count += 1

            plan_status.update(
                label=f"🧠 P:{planning_count} | 🔀 O:{orch_count} | 🛡 C:{critic_count}"
            )

        # ── Render all items AFTER the loop (Streamlit replaces container content) ──
        st.divider()
        for i, item in enumerate(items_log):
            engine = item.get("engine", "")
            idx = item.get("index", 0)
            delta = item.get("delta", "")
            ctx = item.get("trace_context", {})
            is_orch = any(k.startswith("orchestration.") for k in ctx)

            if is_orch or engine == "orchestration":
                engine_label = "🔀 Orchestration"
                engine_color = "#3b82f6"
            elif engine == "planning":
                engine_label = "🧠 Planning"
                engine_color = "#10b981"
            elif engine == "critic":
                engine_label = "🛡 Critic"
                engine_color = "#f59e0b"
            else:
                engine_label = engine
                engine_color = "#6b7280"

            total_so_far = i + 1
            total_all = len(items_log)

            # Header
            col_h1, col_h2, col_h3 = st.columns([1, 3, 2])
            with col_h1:
                term_mark = " 🏁" if item.get("is_terminal") else ""
                st.markdown(f"### #{idx}{term_mark}")
            with col_h2:
                st.markdown(
                    f'<span style="color:{engine_color};font-weight:bold;font-size:1.1em">'
                    f'{engine_label}</span> &nbsp; '
                    f'<code>{item.get("model", "")}</code> &nbsp; '
                    f'<span style="color:#6b7280;font-size:0.85em">'
                    f'测试 {total_so_far}/{total_all}</span>',
                    unsafe_allow_html=True,
                )
            with col_h3:
                if item.get("is_terminal"):
                    st.markdown(f"✅ terminal · `{item.get('finish_reason', '')}`")
                elif item.get("error"):
                    st.markdown(f"❌ `{item.get('error', '')[:60]}`")

            # Delta content
            st.markdown(delta)

            # Trace context badges (always visible)
            if ctx:
                st.caption(_render_trace_badges(ctx), unsafe_allow_html=True)

            # Raw JSON in compact expander
            with st.expander("🔍 原始 trace_context JSON"):
                st.code(json.dumps(ctx, indent=2, ensure_ascii=False), language="json")

            st.divider()

        # ── Stats at the bottom ──
        if pipeline_stats:
            st.markdown("### 📊 Pipeline 统计")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("总 Items", pipeline_stats.get("total_items", len(items_log)))
            c2.metric("Planning", pipeline_stats.get("planning_items", 0))
            c3.metric("Critic", pipeline_stats.get("critic_items", 0))
            c4.metric("耗时 (秒)", f"{pipeline_stats.get('duration_seconds', 0):.3f}s")

        st.session_state.last_pipeline_items = items_log

    elif not run_btn:
        st.info("👆 输入目标后点击「运行 Pipeline」查看 11 条测试的完整日志")
        if st.session_state.last_pipeline_items:
            st.divider()
            st.caption(
                f"上次运行: {len(st.session_state.last_pipeline_items)} items — "
                f"再次点击「运行」重新执行"
            )


# ═══════════════════════════════════════════════════════════════════════════
# Tab 2: Guardrail Scanner
# ═══════════════════════════════════════════════════════════════════════════

with tab2:
    st.markdown("### 16 条 AST 架构规则 + 违规注入对比")

    from demo_guardrails import (
        cleanup_all_violations,
        get_active_violations,
        get_violation_list,
        inject_violation,
        NON_INJECTABLE_RULES,
        run_guardrail_scan,
    )

    # ── Session state for before/after comparison ──
    if "before_scan" not in st.session_state:
        st.session_state.before_scan = None
    if "after_scan" not in st.session_state:
        st.session_state.after_scan = None
    if "injected_info" not in st.session_state:
        st.session_state.injected_info = None

    # ── Violation selector (multi-select) ──
    st.markdown("#### 💉 选择违规类型（可多选）→ 注入 → 对比扫描")
    violation_list = get_violation_list()
    violation_options = {v["id"]: f"{v['title']} — {v['rule_name']}" for v in violation_list}

    # Quick-select buttons — MUST be before the multiselect widget
    # (Streamlit forbids modifying a widget's session_state key after it's rendered)
    compile_ids = {"cross-platform-001", "cross-platform-002", "component-registry"}
    runtime_ids = {"frozen-001", "frozen-002", "frozen-003", "orch-incomplete-keys"}
    all_ids = set(violation_options.keys())

    qc1, qc2, qc3, qc4 = st.columns(4)
    with qc1:
        if st.button("📦 全选 (7项)", use_container_width=True, key="qs_all"):
            st.session_state.violation_multiselect = list(all_ids)
            st.rerun()
    with qc2:
        if st.button("🛡 编译时 (3项)", use_container_width=True, key="qs_compile"):
            st.session_state.violation_multiselect = [k for k in violation_options if k in compile_ids]
            st.rerun()
    with qc3:
        if st.button("🔒 运行时 (4项)", use_container_width=True, key="qs_runtime"):
            st.session_state.violation_multiselect = [k for k in violation_options if k in runtime_ids]
            st.rerun()
    with qc4:
        if st.button("🔄 清空选择", use_container_width=True, key="qs_clear"):
            st.session_state.violation_multiselect = []
            st.rerun()

    col_sel, col_act, col_cln = st.columns([2, 1, 1])
    with col_sel:
        selected_v_list = st.multiselect(
            "选择违规类型（可多选）",
            options=list(violation_options.keys()),
            format_func=lambda x: violation_options[x],
            key="violation_multiselect",
            help="可同时选择多种违规类型，一次性注入并观察多条 Guardrail 规则的拦截效果",
        )
        if selected_v_list:
            descs = []
            for vid in selected_v_list:
                for v in violation_list:
                    if v["id"] == vid:
                        descs.append(f"- **{v['rule_name']}**: {v['description']}")
                        break
            st.caption("\n".join(descs) if descs else "👆 选择违规类型")
        else:
            st.caption("👆 选择一种或多种违规类型")

    with col_act:
        compare_btn = st.button(
            "🔍 注入 + 对比扫描", type="primary", use_container_width=True,
            disabled=len(selected_v_list) == 0,
            help="先跑基线扫描 → 注入所有选中违规 → 再跑扫描 → 对比展示",
        )

    with col_cln:
        clean_btn = st.button("🧹 清理全部", use_container_width=True)

    # ── Handle "注入 + 对比扫描" ──
    if compare_btn:
        # Step 1: Clean and run baseline scan
        cleanup_all_violations()
        st.session_state.active_violation_ids.clear()
        with st.spinner("🔍 运行基线扫描 (注入前)..."):
            st.session_state.before_scan = run_guardrail_scan(str(_PARENT))

        # Step 2: Inject all selected violations
        injected_info_list = []
        for vid in selected_v_list:
            try:
                path, code, desc = inject_violation(vid)
                st.session_state.active_violation_ids.add(vid)
                for v in violation_list:
                    if v["id"] == vid:
                        rule_id = v["rule_id"]
                        break
                else:
                    rule_id = vid
                injected_info_list.append({
                    "path": path,
                    "code": code,
                    "desc": desc,
                    "v_id": vid,
                    "rule_id": rule_id,
                    "title": violation_options.get(vid, vid),
                })
            except Exception as e:
                st.error(f"注入 `{vid}` 失败: {e}")
        st.session_state.injected_info_list = injected_info_list

        # Step 3: Run scan after injection
        with st.spinner("🔍 运行违规扫描 (注入后)..."):
            st.session_state.after_scan = run_guardrail_scan(str(_PARENT))

    # ── Handle cleanup ──
    if clean_btn:
        removed = cleanup_all_violations()
        st.session_state.active_violation_ids.clear()
        st.session_state.before_scan = None
        st.session_state.after_scan = None
        st.session_state.injected_info_list = None
        if removed > 0:
            st.success(f"已清理 {removed} 个违规文件，扫描结果已重置")

    # ── Show active violations ──
    active = get_active_violations()
    if active:
        st.warning(f"⚠️ 当前存在 {len(active)} 个注入的违规文件:")
        for a in active:
            st.caption(f"  • `{a}`")

    # ── Display injected code(s) ──
    injected_info_list = st.session_state.get("injected_info_list") or []
    if injected_info_list:
        st.markdown(f"#### 注入的违规代码 ({len(injected_info_list)} 项)")
        # Use tabs for multiple violations, simple display for single
        if len(injected_info_list) == 1:
            info = injected_info_list[0]
            st.caption(f"文件: `{info['path']}`")
            st.code(info["code"], language="python")
            st.caption(f"触发规则: {info['desc']}")
        else:
            tab_labels = [f"{info['title'][:20]}" for info in injected_info_list]
            vio_tabs = st.tabs(tab_labels)
            for i, info in enumerate(injected_info_list):
                with vio_tabs[i]:
                    st.caption(f"文件: `{info['path']}`")
                    st.code(info["code"], language="python")
                    st.caption(f"触发规则: {info['desc']}")

    # ── Before/After comparison ──
    if st.session_state.before_scan is not None and st.session_state.after_scan is not None:
        before = st.session_state.before_scan
        after = st.session_state.after_scan

        st.divider()
        st.markdown("### 📊 注入前后对比")

        # Summary metrics row
        b_pass = sum(1 for r in before if r["status"] == "PASS")
        b_fail = sum(1 for r in before if r["status"] == "FAIL")
        a_pass = sum(1 for r in after if r["status"] == "PASS")
        a_fail = sum(1 for r in after if r["status"] == "FAIL")

        cm1, cm2, cm3, cm4 = st.columns(4)
        with cm1:
            st.metric("注入前 — 通过", b_pass)
        with cm2:
            st.metric("注入前 — 失败", b_fail, delta=None if b_fail == 0 else str(b_fail),
                      delta_color="off")
        with cm3:
            st.metric("注入后 — 通过", a_pass,
                      delta=f"-{b_pass - a_pass}" if b_pass - a_pass > 0 else None,
                      delta_color="inverse")
        with cm4:
            st.metric("注入后 — 失败", a_fail,
                      delta=f"+{a_fail - b_fail}" if a_fail - b_fail > 0 else None,
                      delta_color="inverse")

        # Side-by-side dataframes
        st.divider()
        left_col, right_col = st.columns(2)

        import pandas as pd

        def _build_comparison_df(results, highlight_rule_ids=None):
            """Build a compact comparison dataframe, highlighting target rules."""
            highlight_rule_ids = highlight_rule_ids or set()
            df_data = []
            for r in results:
                stat = "✅ PASS" if r["status"] == "PASS" else "❌ FAIL"
                highlight = ""
                if r["rule_id"] in highlight_rule_ids and r["status"] == "FAIL":
                    highlight = " ⬅ 目标规则"
                df_data.append({
                    "状态": stat + highlight,
                    "规则": f"{r['rule_id'][:30]}",
                    "层": r["layer"],
                    "违规": r["violations"],
                })
            return pd.DataFrame(df_data)

        # Gather all target rule_ids from injected info
        target_rule_ids = set()
        if injected_info_list:
            for info in injected_info_list:
                target_rule_ids.add(info["rule_id"])

        with left_col:
            st.markdown("#### 🟢 注入前（基线）")
            df_before = _build_comparison_df(before)
            styled_before = df_before.style.map(
                lambda v: "color: #10b981; font-weight: bold" if "PASS" in str(v) else "color: #ef4444; font-weight: bold",
                subset=["状态"]
            )
            st.dataframe(styled_before, use_container_width=True, hide_index=True)

        with right_col:
            st.markdown("#### 🔴 注入后（含违规）")
            df_after = _build_comparison_df(after, highlight_rule_ids=target_rule_ids)
            styled_after = df_after.style.map(
                lambda v: "color: #10b981; font-weight: bold" if "PASS" in str(v) else "color: #ef4444; font-weight: bold",
                subset=["状态"]
            )
            st.dataframe(styled_after, use_container_width=True, hide_index=True)

        # ── Highlight all triggered violations ──
        st.divider()
        triggered_rules = [r for r in after if r["status"] == "FAIL" and r["violations"] > 0]
        if triggered_rules:
            # Header with target match info
            target_triggered = [r for r in triggered_rules if r["rule_id"] in target_rule_ids]
            other_triggered = [r for r in triggered_rules if r["rule_id"] not in target_rule_ids]
            st.markdown(
                f"### 🎯 触发的规则详情 "
                f"（目标命中 {len(target_triggered)} 条，连带触发 {len(other_triggered)} 条）"
            )
            # Show target-triggered rules first (expanded by default)
            for r in target_triggered:
                with st.expander(
                    f"🎯 {r['rule_id']} — {r['name']} ({r['layer']}) — {r['violations']} 处违规",
                    expanded=True,
                ):
                    st.markdown(f"**检测目标**: {r['target']}")
                    if r.get("explain"):
                        st.markdown(f"**设计原理**: {r['explain']}")
                    st.markdown("**违规详情**:")
                    for d in r["details"]:
                        st.error(d)
            # Show other triggered rules (collapsed by default)
            for r in other_triggered:
                with st.expander(
                    f"🔗 {r['rule_id']} — {r['name']} ({r['layer']}) — {r['violations']} 处违规 (连带触发)",
                    expanded=False,
                ):
                    st.markdown(f"**检测目标**: {r['target']}")
                    if r.get("explain"):
                        st.markdown(f"**设计原理**: {r['explain']}")
                    st.markdown("**违规详情**:")
                    for d in r["details"]:
                        st.error(d)
        else:
            st.success("所有规则通过 — 当前注入未触发任何规则（可能是该规则不可注入，见下方说明）")

        # ── Full expandable rules (collapsed by default) ──
        st.divider()
        with st.expander("📖 全部规则详情 (注入后)", expanded=False):
            for r in sorted(after, key=lambda x: (x["status"], x["rule_id"])):
                with st.expander(
                    f"{'❌' if r['status'] == 'FAIL' else '✅'} {r['rule_id']} — {r['name']} ({r['layer']})"
                ):
                    st.markdown(f"**检测目标**: {r['target']}")
                    if r.get("explain"):
                        st.markdown(f"**设计原理**: {r['explain']}")
                    if not r.get("injectable", True):
                        reason = NON_INJECTABLE_RULES.get(r["rule_id"], "")
                        st.info(f"🔒 不可注入演示: {reason}")
                    if r["violations"] > 0:
                        st.markdown("**违规详情**:")
                        for d in r["details"]:
                            st.error(d)
                    else:
                        st.success("无违规")

    elif st.session_state.before_scan is not None:
        # Only baseline scan, no after scan yet
        before = st.session_state.before_scan
        b_pass = sum(1 for r in before if r["status"] == "PASS")
        b_fail = sum(1 for r in before if r["status"] == "FAIL")

        st.divider()
        st.markdown("### 🟢 基线扫描结果 (注入前)")
        c1, c2 = st.columns(2)
        c1.metric("通过", b_pass)
        c2.metric("失败", b_fail)

        import pandas as pd
        df_data = []
        for r in before:
            df_data.append({
                "状态": "✅ PASS" if r["status"] == "PASS" else "❌ FAIL",
                "规则": r["rule_id"][:35],
                "安全层": r["layer"],
                "违规数": r["violations"],
            })
        df = pd.DataFrame(df_data)
        styled = df.style.map(
            lambda v: "color: #10b981; font-weight: bold" if "PASS" in str(v) else "color: #ef4444; font-weight: bold",
            subset=["状态"]
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)

    else:
        st.info("👆 选择违规类型 → 点击「注入 + 对比扫描」查看注入前后的对比效果")


# ═══════════════════════════════════════════════════════════════════════════
# Tab 3: Trace Audit Log
# ═══════════════════════════════════════════════════════════════════════════

with tab3:
    st.markdown("### SQLite 全链路审计日志")

    from demo_trace import build_timeline_data, get_trace_stats, query_traces

    # ── Trace system architecture ──
    with st.expander("📐 审计追踪系统架构", expanded=False):
        st.markdown("""
        #### 追踪数据流

        ```
        Engine Layer                    Observability Layer              Query Layer
        ────────────                   ───────────────────              ───────────

        Planning.plan()                StreamingTraceRecord
        ├─ StreamItem #0  ──────────►  ├─ engine="planning"            Tab 3 (this page)
        ├─ StreamItem #1               ├─ ts_iso                          ├─ st.dataframe
        ├─ StreamItem #2 (orch)        ├─ trace_context_json={...}        ├─ 条件格式渲染
        ├─ StreamItem #3 (orch)        ├─ item_index                       ├─ Key 完整性
        ├─ StreamItem #4 (orch)        ├─ is_terminal                      └─ 时间线图表
        ├─ StreamItem #5 (orch)        └─ dependency_name
        ├─ StreamItem #6 (orch)              │
        ├─ StreamItem #7                      ▼
        └─ StreamItem #8...          SQLiteTraceSink
                                     └─ demo/demo_trace.db
        Critic.evaluate()                  │
        ├─ StreamItem #0                  ▼
        ├─ StreamItem #1           get_trace_stats()
        └─ StreamItem #2           ├─ total_records
                                   ├─ by_engine: {planning, orchestration, critic}
                                   └─ key_completeness: per-engine required key coverage
        ```

        #### 核心设计原则

        | 原则 | 实现 | 安全含义 |
        |------|------|---------|
        | **Write-Ahead** | `run_engine_pipeline()` 在 yield 每条 item 后立即写 SQLite | 即使后续引擎 crash，已产出的记录不丢失 |
        | **Opaque Context** | `trace_context` 是 `Dict[str, Any]`，引擎透明传递不解析 | 引擎层不耦合观测层 schema，可独立演进 |
        | **Fixed Schema** | 18 个 trace key 在 `TRACE_KEY_REGISTRY` 中预声明 | schema drift 被 Guardrail `sink-schema-consistency` 拦截 |
        | **Cross-Tab** | 固定文件路径 `demo/demo_trace.db`（非 `:memory:`） | Streamlit rerun 不丢失数据，Tab 1 写入 Tab 3 可读 |

        #### 18 个 Trace Key 的覆盖率论证

        从 Phase 12 开始，项目引入 **Sufficiency Report** 流程——形式化验证当前 key 集是否充分覆盖所有引擎行为：

        - **Planning 引擎**：需记录步骤编号 (`step_index`)、推理深度 (`reasoning_depth`)、步骤间依赖 (`parent_step_id`)、资源消耗 (`cumulative_tokens`) + 生产者身份 (`agent.identity`) = **5 个 key**
        - **Orchestration 引擎**：需记录 DAG 拓扑 (`dag_node_id`, `parallel_depth`, `merge_ordinal`)、路由决策 (`branch_taken`)、容错行为 (`retry_count`)、资源分配 (`resource_pool_key`) + 生产者身份 = **7 个 key**
        - **Critic 引擎**：需记录质量评分 (`score`)、最终判定 (`verdict`) + 生产者身份 = **3 个 key**
        - **Retrieval**：需记录检索单元 (`chunk_id`)、性能 (`latency_ms`) = **2 个 key**
        - **Component 平台**：通用组件标识 = **1 个 key**

        总计 18 key。v4 Sufficiency Report 确认对 3 种引擎完全充分，无需新增。
        """)

    stats = get_trace_stats(DB_PATH)

    if not stats["exists"] or stats["total_records"] == 0:
        st.info("📭 暂无 Trace 数据。请先到 Tab 1 运行一次引擎 Pipeline。")
        st.caption(f"数据库路径: `{DB_PATH}`")
    else:
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("总记录数", stats["total_records"])
        with c2:
            st.metric("Planning", stats["by_engine"].get("planning", 0))
        with c3:
            st.metric("Critic", stats["by_engine"].get("critic", 0))
        with c4:
            all_comp = stats["key_completeness"]
            total_keys = sum(v["total_keys"] for v in all_comp.values())
            found_keys = sum(v["found"] for v in all_comp.values())
            pct = round(found_keys / total_keys * 100) if total_keys > 0 else 0
            st.metric("Key 完整性", f"{pct}%")

        st.divider()

        engine_filter = st.selectbox(
            "按引擎筛选",
            ["all", "planning", "orchestration", "critic"],
            format_func=lambda x: {"all": "全部引擎", "planning": "Planning",
                                   "orchestration": "Orchestration",
                                   "critic": "Critic"}.get(x, x),
        )

        rows = query_traces(DB_PATH, engine_filter if engine_filter != "all" else None)

        if rows:
            import pandas as pd
            display_rows = []
            for r in rows:
                ctx = r.get("trace_context_parsed", {})
                display_rows.append({
                    "索引": r.get("item_index", ""),
                    "引擎": r.get("engine", ""),
                    "终端": "🏁" if r.get("is_terminal") else "",
                    "内容预览": (r.get("item_delta_preview") or "")[:80],
                    "critic.score": ctx.get("critic.score", ""),
                    "critic.verdict": ctx.get("critic.verdict", ""),
                    "orch.branch": ctx.get("orchestration.branch_taken", ""),
                    "orch.pool": ctx.get("orchestration.resource_pool_key", ""),
                })
            df = pd.DataFrame(display_rows)

            def _verdict_color(val):
                if val == "accept": return "color: #10b981"
                if val == "rework": return "color: #f59e0b"
                if val == "reject": return "color: #ef4444"
                return ""
            styled = df.style.map(_verdict_color, subset=["critic.verdict"])
            st.dataframe(styled, use_container_width=True, hide_index=True)

            # Key completeness
            st.divider()
            st.markdown("### Key 完整性检查")
            for eng, comp in stats["key_completeness"].items():
                pct = round(comp["found"] / comp["total_keys"] * 100) if comp["total_keys"] > 0 else 0
                st.markdown(f"- **{eng}**: {comp['found']}/{comp['total_keys']} keys ({pct}%)")

            # Timeline
            st.divider()
            st.markdown("### ⏱ 引擎执行时间线")
            tl_df = build_timeline_data(rows)
            if tl_df is not None and not tl_df.empty:
                c_left, c_right = st.columns([1, 1])
                with c_left:
                    st.bar_chart(tl_df, x="engine", y="duration", use_container_width=True)
                with c_right:
                    st.dataframe(
                        tl_df.rename(columns={"engine": "引擎", "duration": "Items 数", "item_count": "总计"}),
                        hide_index=True, use_container_width=True,
                    )
        else:
            st.info("当前筛选无匹配记录")


# ═══════════════════════════════════════════════════════════════════════════
# Tab 4: Architecture Documentation
# ═══════════════════════════════════════════════════════════════════════════

with tab4:
    st.markdown("## 📖 Frunsa-Agent 架构文档")
    st.caption("专业解释看 Tab 1 和 Tab 3 的展开面板 — 这里是白话版，给不写代码的人看的。")

    # ── Overview ──
    with st.expander("🏗 项目是什么？", expanded=True):
        st.markdown("""
        **Frunsa-Agent** 是一个实验性的 AI Agent 基础设施项目。核心命题是：

        > **AI Agent 的安全属性可以被工程化地定义、检测和追溯——而非依赖运行时约定或事后审计。**

        换句话说：我不是用防火墙/加密/鉴权来"保护"这个 Agent，而是**把安全属性直接设计进 Agent 的架构里**。

        - **编译时**：代码写完之后，AST 扫描器在 commit 之前检查是否违反架构规则
        - **运行时**：引擎出错不崩溃，而是产出带错误信息的合法数据；API 密钥不散落在引擎代码里
        - **事后**：每次 LLM 调用都完整记录到 SQLite，谁生产的、消耗了多少 token、延时多少——全部可查

        这些不是事后加的"安全功能"，而是从 Phase 1 就写入架构宪法的设计约束。
        """)

    # ── 6 Engines ──
    with st.expander("🧠 6 引擎是什么？(3 stub + 3 LLM)", expanded=False):
        st.markdown("""
        ### 为什么是 6 个？

        项目有 **3 种引擎类型**，每种有 **2 个实现**：

        | 引擎类型 | 职责 | Stub 实现 | LLM 实现 |
        |---------|------|----------|---------|
        | **Planning** | 目标拆解 → 规划执行步骤 | `StubPlanningEngine`（硬编码 5 步流程） | `LLMPlanningEngine`（调 LLM 拆解 + 合成） |
        | **Orchestration** | 并行分发 → 结果合并 | `StubOrchestrationEngine`（asyncio 模拟并行） | `LLMOrchestrationEngine`（LLM 路由 + 重试决策） |
        | **Critic** | 质量评估 → 打分 | `StubCriticEngine`（固定评分 0.85/0.72/0.90） | `LLMCriticEngine`（LLM 评估 + 判定 accept/rework/reject） |

        ### Stub 和 LLM 的关系

        **Stub = 确定性参考实现**。行为完全可预测，CI 测试跑它，毫秒级完成。
        **LLM = 生产引擎**。真正调用大模型，行为非确定性但能力更强。

        二者实现同一个 Protocol（接口），切换只需要一行代码：
        ```python
        # 切换到 LLM 引擎
        engine = StubPlanningEngine(orch_factory=lambda: LLMOrchestrationEngine(adapter))
        ```

        这叫什么？**冗余性**——LLM 挂了，Stub 还能跑。**可更新性**——改一行 lambda 就切换实现。

        ### 面试官视角
        6 个引擎不是"写得多"——而是**每个引擎都有两个独立实现，保证合约的一致性不是靠文档约定，而是靠 Protocol 类型检查 + Guardrail 规则强制执行**。
        """)

    # ── 16 Guardrails ──
    with st.expander("🛡 16 条 Guardrail 规则是什么？", expanded=False):
        st.markdown("""
        ### 不是 Linter，是架构宪法

        Guardrail 是 AST（抽象语法树）级别的代码扫描器。它不检查代码风格——它检查**架构是否被违反**。

        **它怎么工作？**
        1. 读取 `core/` 和 `engines/` 下的所有 `.py` 文件
        2. 解析成 AST（抽象语法树）
        3. 应用 16 条规则，每条规则检查一类架构违反
        4. ERROR 级别违反 → 阻止 commit；WARNING 级别 → 提醒但不阻止

        ### 规则分类

        **编译时安全（8 条）**：在代码运行之前拦截架构违规
        - `cross-platform-001/002`：禁止跨层导入（pipeline ↔ contracts）
        - `frozen-001/002/003`：强制不可变数据模型
        - `engine-interface-purity`：引擎接口必须零实现
        - `component-registry`：组件必须注册
        - `transport-adapter-boundary`：传输层边界检查

        **运行时安全（3 条）**：
        - `stream-isolation`：内部流不泄露给用户
        - `internal-stream-only`：内部流隔离
        - 代码级的 try/except + ResourceContainer 隔离（不在 AST 规则中，在引擎代码里）

        **事后审计（8 条）**：
        - 引擎合约规则：`planning-engine-contract` / `critic-engine-contract` / `orchestration-trace`
        - Trace 完整性：`component-trace` / `component-trace-completeness` / `trace-key-registration` / `trace-key-serializability` / `trace-context-namespace`
        - 推理链覆盖：`chain-coverage`
        - Schema 一致性：`sink-schema-consistency`

        ### 面试官视角
        16 条 Guardrail 既检查"不要做什么"（跨层导入、可变数据），也检查"必须要做什么"（trace key 齐全、组件注册）——**防御性和完整性双管齐下**。
        """)

    # ── 18 Trace Keys ──
    with st.expander("📋 18 个 Trace Key 是什么？", expanded=False):
        st.markdown("""
        ### 一句话：每次 LLM 调用的"身份证"

        每条 StreamItem（引擎产出的最小数据单元）携带一个 `trace_context` 字典，里面是这个 item 的"身份信息"。18 个 key 按前缀分组：

        | 前缀 | 数量 | 典型 Key | 记录什么 |
        |-----|------|---------|---------|
        | `planning.*` | 4 | `step_index`, `reasoning_depth`, `parent_step_id`, `cumulative_tokens` | 规划过程：第几步、推理深度、父步骤、累积 token |
        | `orchestration.*` | 6 | `dag_node_id`, `parallel_depth`, `merge_ordinal`, `branch_taken`, `retry_count`, `resource_pool_key` | 编排过程：DAG 节点、并行深度、归并顺序、分支选择、重试次数、资源池 |
        | `critic.*` | 2 | `score`, `verdict` | 评估结果：质量评分（0-1）、判定（accept/rework/reject） |
        | `retrieval.*` | 2 | `chunk_id`, `latency_ms` | 检索过程：块标识、检索延迟 |
        | `agent.*` | 1 | `identity` | 生产者身份：哪个引擎、哪个版本、具备什么能力 |
        | `component.*` | 2 | (通用组件标识) | 组件平台统一身份 |

        ### 为什么恰好 18 个？

        不是拍脑袋定的。从 Phase 12 开始，项目有一个叫 **Sufficiency Report** 的流程——形式化地验证当前 key 集是否充分覆盖所有引擎行为。v4 报告确认：18 个 key 对 3 种引擎完全充分，不需要新增。

        ### 面试官视角
        这是**非确定性 AI 的确定性管理**——LLM 每次输出不同，但 trace 系统保证每次调用都留下完整的、结构化的审计记录。事后可以还原"谁在什么时候因为什么原因做了什么决定"。
        """)

    # ── 3-Layer Security ──
    with st.expander("🔒 三层可验证安全机制", expanded=False):
        st.markdown("""
        ### 不是"做了三层防御"，而是"每一层都可独立验证"

        | 层 | 时机 | 机制 | 验证方式 | 举例 |
        |---|------|------|---------|------|
        | **编译时** | 代码提交前 | 16 条 AST Guardrail | `python -m guardrails check` | 如果有人写了 `from core.contracts import Chunk` 在 pipeline 文件里，commit 之前就会被拦下 |
        | **运行时** | 引擎执行中 | try/except → error terminal + ResourceContainer | 代码审查 + CI 测试 | 引擎调用 LLM 失败了 → 产出 `StreamItem(error="...", finish_reason="error")`，不 crash |
        | **事后** | 执行完成后 | SQLiteTraceSink + 18 trace keys | SQLite 查询 + Sufficiency Report | "critic 引擎在第 3 次评估时给了 score=0.72, verdict=rework"——可以精确查到 |

        ### 为什么"可验证"很重要？

        传统安全方案依赖"约定"——"大家说好不跨层导入"、"运行时应该不会 crash"。但人多了、时间久了，约定会被忘记。

        这里的每一层都有**机器强制执行**：
        - AST 规则 → 自动扫描，不能绕过
        - try/except → 代码里强制包裹，不会漏
        - SQLite → 自动写入，不依赖人记得记日志

        ### 面试官视角
        这是**安全工程师的工程素养**：不是"我相信这个系统安全"，而是"我可以证明这个系统在哪些条件下安全、在哪些条件下不安全"。
        """)

    # ── Pipeline explained in plain language ──
    with st.expander("🔧 引擎流水线 — 白话版", expanded=False):
        st.markdown("""
        ### 这流水线到底在跑什么？

        想象你给一个 AI 布置任务："帮我设计一个代码安全审计工具"。它不会直接开始写代码——而是经过三个"大脑"依次处理：

        **第一步：Planning（规划大脑）——"我要做什么？"**

        这个大脑拿到你的需求，拆成几个小任务。比如"快速关键词检索"和"语义重排序"，然后决定最多同时开 2 条并行线（`max_parallel_branches=2`）。

        它产出的每条信息都带一张"身份证"（trace_context），上面写着：这是第几步、推理了多深、父步骤是谁、累计花了多少 token。

        **第二步：Orchestration（编排大脑）——"怎么并行做？"**

        规划大脑说"有 2 个小任务要并行做"，编排大脑就去执行。它不是自己干活——它像一个项目经理，把任务分发给工人（资源池），然后收结果。

        每条分发出去的任务都带着 6 个标签：DAG 节点 ID、并行深度、归并顺序、走哪条分支、重试了几次、用的什么资源池。这样事后可以精确还原"谁在什么时候分配了什么给谁"。

        **第三步：Critic（评判大脑）——"做得好不好？"**

        前面两个大脑干完活，产出结果交给评判大脑打分。它不是笼统地说"不错"或"不行"——而是分三个维度打分：
        - 任务拆解是否合理？(decomposition)
        - 并行分发是否恰当？(dispatch)
        - 结果合并是否完整？(synthesis)

        每个维度都有一个 0-1 的分数和一个判定：accept（通过）、rework（返工）、reject（拒绝）。

        ### 为什么要三个大脑而不是一个？

        一个大脑"全包"有三个问题：
        1. **责任不清**：出了问题不知道是"想错了"还是"做错了"还是"评错了"
        2. **不可替换**：想换个更好的规划方式？对不起，所有逻辑搅在一起
        3. **不可审计**：无法独立追踪每个环节的决策质量

        三个独立大脑的好处：
        - **可替换**：换 Planning 引擎不影响 Orchestration 和 Critic
        - **可审计**：每个大脑的每条决策都有独立 trace
        - **可容错**：Planning 挂了，Critic 还能评估之前的结果

        ### 什么是 Mock 模式？

        Tab 1 默认跑的是 Mock 模式——不调真实大模型，用提前写好的固定文本模拟 LLM 输出。好处：
        - 不需要 API Key
        - 每次跑结果一模一样（确定性）
        - 0.1 秒跑完全程

        这也是为什么 CI 测试（673 个）能在 27 秒跑完——全部用 Mock，不依赖外部 API。
        """)

    # ── Trace explained in plain language ──
    with st.expander("📋 审计追踪 — 白话版", expanded=False):
        st.markdown("""
        ### 为什么需要"追踪"？

        LLM 的输出是不确定的——同样的问题问两次，答案可能不一样。这在安全领域是个大问题：如果出了事故，你怎么知道 AI 当时是怎么决策的？

        追踪系统就是 AI 的"行车记录仪"——每一次引擎调用、每一条数据产出、每一个决策，都自动记到 SQLite 数据库里。

        ### 它记了什么？

        不是记"这个函数被调用了"这种技术日志，而是记**语义信息**：

        | 记录内容 | 白话解释 | 安全用途 |
        |---------|---------|---------|
        | `planning.step_index` | "这是第几步规划" | 还原规划路径 |
        | `orchestration.branch_taken` | "走了哪条分支" | 追溯路由决策 |
        | `orchestration.retry_count` | "重试了几次" | 发现不稳定调用 |
        | `critic.score` | "质量评分多少" | 评估模型偏差 |
        | `critic.verdict` | "通过/返工/拒绝" | 统计拒绝率趋势 |
        | `agent.identity` | "哪个引擎版本评的" | 版本对比分析 |
        | `retrieval.latency_ms` | "检索花了多少毫秒" | 性能瓶颈定位 |

        ### 怎么保证每一条都记了？

        不是靠"开发者记得写日志"——而是靠 **Guardrail 规则在 CI 阶段检查**。规则 `orchestration-trace-completeness` 会扫描代码，确认 Orchestration 引擎产出的每条数据都包含全部 6 个必需的 key。少了任何一个——commit 直接拦截。

        ### 记了之后能干什么？

        1. **查谁干了什么**：`SELECT * FROM trace_records WHERE engine='critic'` —— 所有评分记录一秒列出
        2. **查谁没干什么**：Key 完整性检查发现缺失字段 —— 说明引擎实现有 bug
        3. **还原决策过程**：按时间顺序回放 Planning → Orchestration → Critic 的完整链条
        4. **对比版本差异**：按 `agent.identity.version` 分组统计评分分布 —— 发现新版模型是否比旧版更严格

        ### 为什么存 SQLite 而不是 JSON 文件？

        - JSON 文件：人眼可读，但跨页查询、条件筛选、聚合统计全都要写代码
        - SQLite：任意 SQL 查询、零配置、文件级单文件、支持并发读

        而且 SQLite 文件可以用任何 SQL 工具打开——不只是这个 Streamlit 页面。
        """)

    # ── Case Studies ──
    with st.expander("📚 典型案例", expanded=False):
        st.markdown("""
        ### 案例 1：如果有人在 pipeline 里直接 import 了 contracts 的类型？

        **真实场景**：新来的开发者不知道三层架构规则，在 `core/pipeline/optimizer.py` 里写了：
        ```python
        from core.contracts.generation import Chunk
        ```

        **会发生什么？**
        1. `git commit` → pre-commit hook 触发 `python -m guardrails check`
        2. `cross-platform-001` 规则扫描 → 发现 pipeline 文件导入了 contracts 类型 → ERROR
        3. Commit 被阻止。开发者看到错误信息，修改代码，通过 contracts 的公开 Protocol 接口来获取数据。

        **你可以在 Tab 2 亲自试试**：选择"跨层导入违规"→ 注入 → 运行扫描 → 看到拦截。
        """)

        st.markdown("""
        ### 案例 2：如果 LLM 调用失败了会怎样？

        **真实场景**：生产环境中 OpenAI API 返回 500 错误。

        **会发生什么？**
        1. `GenerationAdapter.generate()` 抛出异常
        2. 引擎的 `try/except` 捕获
        3. 引擎产出 `StreamItem(error="...", finish_reason="error", trace_context={...})`——带完整 trace
        4. 上游调用者收到这个 error item，决定下一步（重试？降级？告知用户？）
        5. SQLiteTraceSink 已经记录了这次失败——事后可以统计失败率和原因

        **不会发生什么？** 进程不会 crash。其他引擎不受影响。Trace 数据不会丢失。
        """)

        st.markdown("""
        ### 案例 3：怎么证明 Critic 引擎的评分不是瞎给的？

        **真实场景**：面试官问"你怎么知道 Critic 给了公平的评分？"

        **能回答什么？**
        1. 每个 Critic item 的 `trace_context` 里同时有 `critic.score`、`critic.verdict` 和 `agent.identity`
        2. Tab 3 可以精确查询：`SELECT * FROM trace_records WHERE engine='critic'`——看到所有评估记录
        3. 如果怀疑评分异常，可以按时间回放：输入是什么 → 输出是什么 → 评分多少 → 哪个引擎版本评的
        4. 如果将来发现评分模型有 bias，可以通过 `agent.identity.version` 追溯到具体版本，做对比分析

        **关键点**：不是"我相信 LLM 评分公平"，而是"我可以追溯每一次评分，审计其合理性"。
        """)

    # ── Q&A ──
    with st.expander("❓ 常见问题 (Q&A)", expanded=False):
        st.markdown("""
        **Q: 这个项目能在生产环境用吗？**

        A: 目前是实验平台，不是产品。但架构设计考虑了生产级约束：Protocol 抽象保证引擎可替换、Guardrail 强制执行架构规则、SQLiteTraceSink 提供审计能力——这些都是生产环境需要的基础设施。673 个测试保证行为正确性。

        ---

        **Q: 为什么用 AST 扫描而不是运行时检查？**

        A: 两个原因。一是成本——AST 扫描在 CI 阶段完成，零运行时开销。二是安全——代码没跑之前就能发现问题，符合"安全左移"原则。当然，AST 扫描不能检测运行时行为（这是已知局限 L-02）。

        ---

        **Q: MockBackend 能替代真实 LLM 测试吗？**

        A: 不能完全替代。MockBackend 的价值是确定性——确保 CI 测试不受 LLM 非确定性的影响，每次跑结果一致。它测试的是"引擎逻辑是否正确"，不是"LLM 输出质量如何"。真实 LLM 的评测需要独立的验证流程（已知局限 L-06）。

        ---

        **Q: 三个引擎之间的关系是什么？**

        A: Planning 负责"想"（目标拆解 → 规划步骤），Orchestration 负责"做"（并行分发 → 合并结果），Critic 负责"评"（评估输出质量）。Planning 内部调用 Orchestration（通过 factory DI），Critic 独立评估 Planning 的产出。三者都实现统一的 Protocol 签名：`async fn(context, deadline, pace_config) -> AsyncIterator[StreamItem]`。

        ---

        **Q: 为什么叫 "Frunsa"？**

        A: Framework for Universal Secure AI Agent 的缩写。也隐含 "frugal + safe" 的意思——精简且安全。

        ---

        **Q: Phase 19 会做什么？**

        A: Phase 19 规划了多级 DAG 并行（当前只有单级 fan-out）和 WAL 模式 SQLite。但项目优先级取决于业务需求——这是一个研究/实验平台，不是商业产品 road map。

        ---

        **Q: 如果我想学习这个项目，从哪里开始？**

        A: 推荐顺序：
        1. 先看 `PLAN.md` 了解整体架构演进
        2. 看 `CLAUDE.md` 了解架构不变式
        3. 看 `.ai_reasoning/index.yaml` 找感兴趣的推理链
        4. 看 `engines/planning/stub.py` 理解最简单的引擎实现
        5. 看 `tests/conformance/` 了解如何测试引擎合约
        """)
