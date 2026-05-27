"""Guardrail scanner + violation library for live demo.

Supports multiple violation types, each targeting a specific AST rule.
Temp files injected into scanned directories, cleaned up after demo.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from guardrails.checker import GuardrailChecker
from guardrails.report import Severity

# ── Violation Library ────────────────────────────────────────────────────

@dataclass
class ViolationSpec:
    """A single injectable violation targeting a specific guardrail rule."""
    v_id: str
    title: str
    description: str
    rule_id: str
    rule_name: str
    target_dir: Path   # where to inject (must be scanned by the rule)
    filename: str
    code: str

    @property
    def filepath(self) -> Path:
        return self.target_dir / self.filename


def _pipeline_dir():
    return _PARENT / "core" / "pipeline"

def _contracts_dir():
    return _PARENT / "core" / "contracts"

def _steps_dir():
    return _PARENT / "core" / "steps"

def _orch_dir():
    return _PARENT / "engines" / "orchestration"


VIOLATION_LIBRARY: List[ViolationSpec] = [
    ViolationSpec(
        v_id="cross-platform-001",
        title="跨层导入违规",
        description="core/pipeline/ 直接导入 core/contracts/ 的领域类型，违反三层平台隔离宪法",
        rule_id="cross-platform-001",
        rule_name="跨层导入检测 (pipeline→contracts)",
        target_dir=_pipeline_dir(),
        filename="_tmp_violation_cross.py",
        code='''\
"""TEMP VIOLATION — do NOT commit."""

# VIOLATION: core/pipeline/ imports domain types from core/contracts/
# Guardrail: cross-platform-001 (ERROR)
from core.contracts.generation import Chunk, RetrievalResult

_ = Chunk
_ = RetrievalResult
''',
    ),
    ViolationSpec(
        v_id="cross-platform-002",
        title="反向跨层导入违规",
        description="core/contracts/ 反向导入 core/pipeline/ 的编排类型，违反三层平台隔离宪法",
        rule_id="cross-platform-002",
        rule_name="跨层导入检测 (contracts→pipeline)",
        target_dir=_contracts_dir(),
        filename="_tmp_violation_reverse.py",
        code='''\
"""TEMP VIOLATION — do NOT commit."""

# VIOLATION: core/contracts/ imports orchestration types from core/pipeline/
# Guardrail: cross-platform-002 (ERROR)
from core.pipeline.tracing import PipelineRunner, StepConfig

_ = PipelineRunner
_ = StepConfig
''',
    ),
    ViolationSpec(
        v_id="frozen-001",
        title="非不可变 dataclass",
        description="@dataclass 未设置 frozen=True，数据可被运行时篡改，破坏安全审计路径确定性",
        rule_id="frozen-001",
        rule_name="不可变数据模型 (frozen=True)",
        target_dir=_contracts_dir(),
        filename="_tmp_violation_mutable.py",
        code='''\
"""TEMP VIOLATION — do NOT commit."""

from dataclasses import dataclass
from typing import Dict

# VIOLATION: @dataclass without frozen=True
# Guardrail: frozen-001 (ERROR — has dict field = mutation risk)
@dataclass
class MutableConfig:
    settings: Dict[str, int]
    label: str = "unsafe"
''',
    ),
    ViolationSpec(
        v_id="frozen-002",
        title="dict 字段无 MappingProxyType",
        description="frozen dataclass 中包含裸 dict 字段，但 __post_init__ 未用 MappingProxyType 封装",
        rule_id="frozen-002",
        rule_name="MappingProxyType 防御",
        target_dir=_contracts_dir(),
        filename="_tmp_violation_noproxy.py",
        code='''\
"""TEMP VIOLATION — do NOT commit."""

from dataclasses import dataclass, field
from typing import Dict

# VIOLATION: frozen dataclass with bare dict field, no MappingProxyType in __post_init__
# Guardrail: frozen-002 (ERROR)
@dataclass(frozen=True)
class UnsafeFrozen:
    options: Dict[str, str] = field(default_factory=dict)
''',
    ),
    ViolationSpec(
        v_id="frozen-003",
        title="__setattr__ 绕过检测",
        description="在 __post_init__ 之外使用 object.__setattr__ 绕过 frozen 保护",
        rule_id="frozen-003",
        rule_name="__setattr__ 绕过检测",
        target_dir=_steps_dir(),
        filename="_tmp_violation_setattr.py",
        code='''\
"""TEMP VIOLATION — do NOT commit."""

from dataclasses import dataclass

@dataclass(frozen=True)
class Bypassed:
    x: int = 0

# VIOLATION: object.__setattr__ outside __post_init__
# Guardrail: frozen-003 (ERROR)
obj = Bypassed(x=1)
object.__setattr__(obj, "x", 42)
''',
    ),
    ViolationSpec(
        v_id="component-registry",
        title="未注册组件",
        description="实现了 run() + health_check() 但未添加 @register_component 装饰器",
        rule_id="component-registry",
        rule_name="组件注册完整性",
        target_dir=_steps_dir(),
        filename="tmp_violation_unreg.py",
        code='''\
"""TEMP VIOLATION — do NOT commit."""

# VIOLATION: class with run() + health_check() but no @register_component
# Guardrail: registry-001 (WARNING)
# NOTE: filename must NOT start with _ (rule skips _-prefixed files)
class UnregisteredStep:
    """This step looks like a component but is not registered."""

    def run(self, state, **kwargs):
        return state

    def health_check(self):
        return True
''',
    ),
    ViolationSpec(
        v_id="orch-incomplete-keys",
        title="Orchestration 未注册 Trace Key",
        description="注入一个不在 TRACE_KEY_REGISTRY 中的伪造 orchestration.* key，触发污染检测",
        rule_id="orchestration-trace",
        rule_name="Orchestration Trace 完整性",
        target_dir=_orch_dir(),
        filename="tmp_violation_orch_keys.py",
        code='''\
"""TEMP VIOLATION — do NOT commit."""

# VIOLATION: unregistered orchestration.* key injected into engine source
# Guardrail: orchestration-trace-completeness-002 (ERROR — pollution detection)
# The key "orchestration.fake_injected_key" is NOT in TRACE_KEY_REGISTRY
# NOTE: must use a Call node with trace_context= kwarg for AST detection

from core.contracts.generation import StreamItem

_ = StreamItem(
    delta="test",
    index=0,
    model="orch-stub",
    trace_context={
        "orchestration.branch_taken": "fast_path",
        "orchestration.retry_count": 0,
        "orchestration.fake_injected_key": "pollution!",
        "agent.identity": {"id": "test"},
    },
)
''',
    ),
]


# ── Rule Info Registry ───────────────────────────────────────────────────

RULE_INFO: Dict[str, Dict[str, str]] = {
    "cross-platform-001": {
        "name": "跨层导入检测 (pipeline→contracts)",
        "layer": "编译时",
        "target": "core/pipeline/ 禁止导入 core/contracts/ 领域类型",
        "explain": "三层平台架构的宪法级规则。pipeline 层处理数据流编排，contracts 层定义数据类型——pipeline 引入 contracts 类型会导致编排逻辑与数据类型耦合，破坏可更新性。",
    },
    "cross-platform-002": {
        "name": "跨层导入检测 (contracts→pipeline)",
        "layer": "编译时",
        "target": "core/contracts/ 禁止导入 core/pipeline/ 编排类型",
        "explain": "反向隔离——contracts 层定义纯数据类型，导入 pipeline 的编排类型会污染类型系统，使 contracts 失去独立演进能力。",
    },
    "frozen-001": {
        "name": "不可变数据模型 (frozen=True)",
        "layer": "运行时",
        "target": "所有 @dataclass 必须 frozen=True",
        "explain": "AI Agent 的数据在多个引擎间流转，如果可变，一个引擎的修改可能污染另一个引擎的输入。frozen=True 保证数据在流转中不被篡改——这是安全审计的基础。",
    },
    "frozen-002": {
        "name": "MappingProxyType 防御",
        "layer": "运行时",
        "target": "dict 字段必须用 MappingProxyType 封装",
        "explain": "frozen=True 防止属性赋值，但阻止不了 dict 的 .update()。MappingProxyType 提供真正的只读视图——防御 Python 运行时绕过。",
    },
    "frozen-003": {
        "name": "__setattr__ 绕过检测",
        "layer": "运行时",
        "target": "object.__setattr__ 仅限 __post_init__ 内使用",
        "explain": "Python 的 object.__setattr__ 可以绕过 frozen 限制直接修改属性。规则检测所有在 __post_init__ 之外的此类调用——防止'看似不可变实则可变'的假安全。",
    },
    "stream-isolation": {
        "name": "流隔离",
        "layer": "运行时",
        "target": "internal stream 不泄露到 user-facing stream",
        "explain": "引擎内部的调试流不应暴露给最终用户——防止内部状态信息泄露。internal stream 和 user-facing stream 有独立的传输通道。",
    },
    "chain-coverage": {
        "name": "推理链覆盖",
        "layer": "事后",
        "target": "新 core module 必须有对应 reasoning chain",
        "explain": "每个 core/ 模块的设计决策必须记录在 .ai_reasoning/ 推理链中。AST 扫描检测新增的 core module 是否有对应的 reasoning chain——保证架构决策可追溯。",
    },
    "component-registry": {
        "name": "组件注册完整性",
        "layer": "编译时",
        "target": "所有组件必须在 Registry 中注册",
        "explain": "实现了 run() + health_check() 的 Step 类必须通过 @register_component 注册。未注册的组件无法被 PipelineRunner 发现和调度——AST 扫描在 CI 阶段拦截漏注册。",
    },
    "component-trace": {
        "name": "组件 Trace Key 完整性",
        "layer": "事后",
        "target": "组件 trace key 完整性检查",
        "explain": "每个组件产出的 trace key 必须完整。如果某个组件的 trace 记录缺少关键字段，SQLiteTraceSink 的查询将无法还原全链路——AST 扫描确保每个组件类型都产出其声明的全部 key。",
    },
    "engine-interface-purity": {
        "name": "引擎接口纯度",
        "layer": "编译时",
        "target": "interface.py 必须零实现（仅 Protocol 定义）",
        "explain": "引擎的 interface.py 是合约面（Protocol 定义 + dataclass），不能包含任何实现代码（函数体只能是 ...）。实现只能出现在 stub.py 或 llm.py——保证合约与实现的彻底分离。",
    },
    "orchestration-trace": {
        "name": "Orchestration Trace 完整性",
        "layer": "事后",
        "target": "所有 6 个 orchestration.* keys 必须存在",
        "explain": "Orchestration 引擎产出 6 个必需的 trace key：dag_node_id、parallel_depth、merge_ordinal、branch_taken、retry_count、resource_pool_key。缺少任何一个，事后无法还原并行分发决策——AST 扫描确保源码中 6 key 齐全。",
    },
    "planning-engine-contract": {
        "name": "Planning Engine 合约",
        "layer": "编译时",
        "target": "planning.* keys + agent.identity 完整性",
        "explain": "Planning 引擎的每个 StreamItem 必须携带 planning.step_index、reasoning_depth、parent_step_id、cumulative_tokens 和 agent.identity——确保规划过程的每一步都可独立审计。",
    },
    "critic-engine-contract": {
        "name": "Critic Engine 合约",
        "layer": "编译时",
        "target": "critic.* keys + agent.identity 完整性",
        "explain": "Critic 引擎的每个评估结果必须携带 critic.score、critic.verdict 和 agent.identity——确保评估来源和结论可追溯，防止虚假评分。",
    },
    "trace-key-registration": {
        "name": "Trace Key 注册完整性",
        "layer": "事后",
        "target": "所有 trace key 必须在 Registry 声明",
        "explain": "所有 trace key 必须在 TRACE_KEY_REGISTRY 中注册——防止引擎开发者随意添加 ad-hoc key 导致日志 schema 膨胀和跨团队理解不一致。",
    },
    "trace-key-serializability": {
        "name": "Trace Key 序列化安全",
        "layer": "事后",
        "target": "trace_context 值必须可 JSON 序列化",
        "explain": "所有 trace_context 的 value 必须是 JSON 可序列化类型——防止 runtime 对象（如闭包、生成器）被放入 trace 导致序列化失败和日志丢失。",
    },
    "sink-schema-consistency": {
        "name": "Sink Schema 一致性",
        "layer": "事后",
        "target": "Sink schema 与 Trace Key Registry 一致",
        "explain": "SQLiteTraceSink 的表结构必须与声明的 schema 一致——防止代码中的表定义与数据库初始化脚本的 drift。Schema-first 设计保证审计数据的可靠性。",
    },
    "trace-context-namespace": {
        "name": "Trace Context 命名空间",
        "layer": "事后",
        "target": "trace key 命名空间隔离",
        "explain": "不同引擎的 trace key 使用独立前缀（planning.* / orchestration.* / critic.* / retrieval.* / agent.* / component.*）——防止跨引擎 key 碰撞导致审计数据覆盖。E2E 测试验证 critic.* 不会出现在 orchestration 记录中。",
    },
    "transport-adapter-boundary": {
        "name": "Transport Adapter 边界",
        "layer": "编译时",
        "target": "Transport 层 adapter 边界检查",
        "explain": "Transport 层的 adapter 不能绕过 protocol 直接访问 pipeline 内部——AST 扫描确保所有 adapter 调用都经过正式的接口边界，防止紧耦合。",
    },
    "component-trace-completeness": {
        "name": "Component Trace 完整性",
        "layer": "事后",
        "target": "组件平台通用 trace key 完整性",
        "explain": "组件平台（Component Platform）的通用 trace key 必须齐全——确保任意类型的组件在 trace 日志中都有统一的身份标识和耗时记录。",
    },
}

# Rules that CANNOT be demonstrated with temp-file injection (explain why)
NON_INJECTABLE_RULES: Dict[str, str] = {
    "engine-interface-purity": "扫描 engines/**/interface.py 具体文件。注入临时文件不会被识别为 interface.py，修改真实 interface.py 会破坏项目。CI 环境通过 guardrail 自动化验证。",
    "planning-engine-contract": "扫描 planning engine 源码中的实际 trace key 产出。临时文件不会被执行 AST 扫描（规则定位到 engines/planning/ 目录的 .py 文件）。",
    "critic-engine-contract": "同 planning-engine-contract，扫描 engines/critic/ 目录。临时文件不会被匹配。",
    "trace-key-registration": "比较源码中的 trace key 与 Registry 声明。需要在多个现有文件中修改 key 才能触发。属于跨文件一致性检查，单文件注入无法复现。",
    "trace-key-serializability": "检查 trace_context 值类型。临时文件的 trace_context 会被 AST 解析，但规则设计为扫描引擎目录。",
    "sink-schema-consistency": "比较 sink_schema.py 声明与实际建表 SQL。需要修改 schema 文件才能触发。属于配置级规则。",
    "trace-context-namespace": "检查跨引擎 key 前缀隔离。需要多个引擎文件同时存在越界 key。单文件注入无法触发。",
    "transport-adapter-boundary": "检查 transport 层 adapter 调用链。临时文件不在 transport 目录不会被扫描。",
    "stream-isolation": "检查流隔离模式。临时文件不会被扫描（规则定位到具体的 stream 实现文件）。",
    "chain-coverage": "检测 core/ 目录新增模块是否有对应 .ai_reasoning/ 推理链。临时文件可能触发（如果放在 core/ 子目录），但需要同时检查 .ai_reasoning/ 文件缺失。",
    "component-trace": "检查组件平台 trace key 完整性。规则扫描特定组件文件。",
    "component-trace-completeness": "同 component-trace。",
}


# ── Public API ───────────────────────────────────────────────────────────

def run_guardrail_scan(root_path: str | None = None) -> List[Dict[str, Any]]:
    """Run all guardrail rules and return structured results."""
    root = Path(root_path) if root_path else _PARENT
    checker = GuardrailChecker(root=root, min_severity=Severity.WARNING)
    report = checker.run()

    rule_violations: Dict[str, List[str]] = {}
    for v in report.violations:
        key = _map_rule_id(v.rule_id)
        if key not in rule_violations:
            rule_violations[key] = []
        rule_violations[key].append(f"{v.message} ({v.file}:{v.line})")

    results: List[Dict[str, Any]] = []
    for rule_id, info in sorted(RULE_INFO.items()):
        violations_list = rule_violations.get(rule_id, [])
        results.append({
            "rule_id": rule_id,
            "name": info["name"],
            "layer": info["layer"],
            "target": info["target"],
            "explain": info.get("explain", ""),
            "status": "PASS" if not violations_list else "FAIL",
            "violations": len(violations_list),
            "details": violations_list,
            "injectable": rule_id not in NON_INJECTABLE_RULES,
        })

    return results


def get_violation_list() -> List[Dict[str, Any]]:
    """Return list of available violations for the UI dropdown."""
    return [
        {"id": v.v_id, "title": v.title, "description": v.description,
         "rule_id": v.rule_id, "rule_name": v.rule_name}
        for v in VIOLATION_LIBRARY
    ]


def inject_violation(violation_id: str | None = None) -> Tuple[str, str, str]:
    """Inject a violation and return (path, code, rule_description)."""
    v = _find_violation(violation_id)
    v.target_dir.mkdir(parents=True, exist_ok=True)
    v.filepath.write_text(v.code, encoding="utf-8")
    return str(v.filepath), v.code, f"{v.rule_name}: {v.description}"


def cleanup_all_violations() -> int:
    """Remove ALL temp violation files. Returns count removed."""
    removed = 0
    for v in VIOLATION_LIBRARY:
        if v.filepath.exists():
            v.filepath.unlink()
            removed += 1
    return removed


def get_active_violations() -> List[str]:
    """Return list of currently active (injected) violation file paths."""
    return [str(v.filepath) for v in VIOLATION_LIBRARY if v.filepath.exists()]


# ── Internal helpers ─────────────────────────────────────────────────────

def _find_violation(v_id: str | None) -> ViolationSpec:
    if v_id is None:
        return VIOLATION_LIBRARY[0]
    for v in VIOLATION_LIBRARY:
        if v.v_id == v_id:
            return v
    return VIOLATION_LIBRARY[0]


def _map_rule_id(rule_id: str) -> str:
    mapping = {
        "cross-platform-001": "cross-platform-001",
        "cross-platform-002": "cross-platform-002",
        "frozen-001": "frozen-001",
        "frozen-002": "frozen-002",
        "frozen-003": "frozen-003",
        "registry-001": "component-registry",
        "orchestration-trace-completeness-001": "orchestration-trace",
        "orchestration-trace-completeness-002": "orchestration-trace",
        "cross-platform-imports": "cross-platform-001",
        "frozen-dataclass-integrity": "frozen-001",
        "component-registration-coverage": "component-registry",
        "reasoning-chain-coverage": "chain-coverage",
        "user-facing-stream-isolation": "stream-isolation",
        "internal-stream-only": "stream-isolation",
        "transport-adapter-boundary": "transport-adapter-boundary",
        "engine-interface-purity": "engine-interface-purity",
        "trace-context-namespace": "trace-context-namespace",
        "trace-key-serializability": "trace-key-serializability",
        "component-trace-completeness": "component-trace",
        "orchestration-trace-completeness": "orchestration-trace",
        "planning-engine-contract": "planning-engine-contract",
        "critic-engine-contract": "critic-engine-contract",
        "trace-key-registration": "trace-key-registration",
        "sink-schema-consistency": "sink-schema-consistency",
        "trace-key-registration-001": "trace-key-registration",
        "trace-key-registration-002": "trace-key-registration",
        "orchestration-trace-completeness-002": "orchestration-trace",
    }
    return mapping.get(rule_id, rule_id)
