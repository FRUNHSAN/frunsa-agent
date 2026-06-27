# 13 — 适配器实现规范 + 内核版本兼容性协议

**定位**：面向需要为内核编写 Observer/Actuator 适配器的人，以及需要跨版本维护这些适配器的人。  
**前提**：你已经按 [11-migration](./11-migration-guide.md) 拆出了内核，按 [12-bus](./12-bus-manufacturing-guide.md) 接上了通信层。现在是最后一步——让数据正确地流入流出内核。

> 上游文档：[11-migration-guide.md](./11-migration-guide.md) → [12-bus-manufacturing-guide.md](./12-bus-manufacturing-guide.md) → **本文档**

---

## 一、适配器的角色：内核与外界的翻译层

```
内核 (纯 float)              ←→  适配器  ←→  外界 (传感器/执行器/通信协议)
StateVector                      CPU Adapter                 Observer / Actuator
ControlFrame                     Kernel Adapter              ROS2 / MQTT / HTTP
```

适配器是双向翻译器。内核只认识 float 和 enum——适配器把外界的一切翻译成 float，再把内核的 float 翻译回外界能执行的指令。

**参考实现**：[`mainboard/cpu/adapter.py`](../mainboard/cpu/adapter.py) —— 10 个标量 → 16 维 StateVector 的纯函数映射。

---

## 二、三类适配器及其实现契约

### 类型 1：Observer Adapter（外界 → 内核）

```
输入：原始传感器数据 / NL 文本 / API 响应
输出：ObservationResult → StateVector（只写 INSTANT 维度）
```

**强制实现**：
```python
class MyObserver:
    # 适配器元信息（必须声明）
    ADAPTER_VERSION: str = "1.0.0"
    COMPATIBLE_KERNEL_VERSIONS: str = ">=1.0.0, <2.0.0"
    observer_latency_ms: float = 3.0   # 感知延迟预算
    
    def observe(self, raw_input) -> ObservationResult:
        """把外界数据翻译成 ObservationResult → 最终填入 StateVector"""
        ...
```

**强制规则**：
- **只写 `instant_` 前缀的维度**。`ode_` 前缀的维度由 ODE 积分器独占（铁律 #2）
- **必须声明 `observer_latency_ms`** ——内核在 ControlFrame 中标注 `effective_timestamp = now - latency`
- **返回 ObservationResult（非直接 StateVector）** ——由 CPU Adapter 完成最终的类型映射

**禁止**：写 ODE 维度、修改 DERIVED 维度、在 observe() 中有副作用（网络请求 / 文件 I/O 必须是外部的，observe() 只做纯翻译）

> 参见：[01-onboarding-for-collaborators.md](./01-onboarding-for-collaborators.md) — "如果你做感知"节

---

### 类型 2：Actuator Adapter（内核 → 外界）

```
输入：ControlFrame { action, params, safety_flag, trace_id }
输出：电机指令 / ROS2 Action / HTTP Response / NL 文本
```

**强制实现**：
```python
class MyActuator:
    ADAPTER_VERSION: str = "1.0.0"
    COMPATIBLE_KERNEL_VERSIONS: str = ">=1.0.0, <2.0.0"
    actuation_latency_ms: float = 1.0
    
    def execute(self, cf: ControlFrame) -> ActuationResult:
        """把 ControlFrame 翻译成外界可执行的指令"""
        if cf.safety_flag == SafetyFlag.RED:
            return self._emergency_stop()
        ...
```

**强制规则**：
- **必须声明 `actuation_latency_ms`**
- **禁止修改 ControlFrame 的 action 或 safety_flag** ——适配器是翻译器，不是决策器
- **safety_flag == RED 必须无条件紧急停止** ——不得执行任何其他动作

**禁止**：修改内核决策、在 execute() 中重新做路由（内核已经做了）、忽略 safety_flag

---

### 类型 3：Bus Adapter（内核 ↔ 通信层）

每条总线有独立的 Protocol 签名。详见 [12-bus-manufacturing-guide.md](./12-bus-manufacturing-guide.md)。

---

## 三、适配器的注册与发现

```
Mainboard 启动时：
  AdapterRegistry.discover("my_project/adapters/")
  → 扫描目录下所有实现了 AdapterProtocol 的类
  → 注册到 Registry（name + version + capability_flags）
  → 内核启动时从 Registry 获取默认适配器
  → 可通过配置文件 / 环境变量在运行时替换
```

```python
# 注册示例
from mainboard.adapter_registry import AdapterRegistry
AdapterRegistry.register('observer', 'social_nav_v1', SocialNavObserver)
AdapterRegistry.register('actuator', 'omni_wheel_v2', OmniWheelActuator)
```

---

## 四、内核版本协议（Kernel Version Protocol）

### 4.1 版本号语义

```
主版本号.次版本号.修订号
MAJOR.MINOR.PATCH

MAJOR：协议不兼容的变更（StateVector 维度删除、ControlFrame 字段删除）
MINOR：协议兼容的新增（StateVector 末尾追加新维度、新增可选字段）
PATCH：纯 bugfix，协议不变
```

**当前协议版本**：`1.0.0`

### 4.2 版本声明位置

```
protocol/__version__.py        → KERNEL_PROTOCOL_VERSION = "1.0.0"
每个适配器                       → COMPATIBLE_KERNEL_VERSIONS = ">=1.0.0, <2.0.0"
```

### 4.3 启动时的版本协商

```python
# kernel_step() 入口：
def kernel_step(ks: KernelState, sv: StateVector) -> ControlFrame:
    # 1. 检查 StateVector 携带的协议版本号
    if sv._protocol_version < MIN_COMPATIBLE_VERSION:
        raise VersionError(f"StateVector v{sv._protocol_version} too old")
    if sv._protocol_version > KERNEL_PROTOCOL_VERSION:
        raise VersionError(f"StateVector v{sv._protocol_version} from future")
    # 2. 在兼容范围内 → 通过
    # 3. 如果次版本号不同但主版本号相同 → 新维度用默认值
```

### 4.4 版本迁移路径

**主版本升级（如 1.x → 2.0）**：
- 发布迁移指南（本文件的版本附录，记录每个 MAJOR 的变更）
- 提供兼容适配器（2.0 内核 + 1.x 适配器 = 兼容层自动映射缺失字段）
- 废弃窗口：1.x 适配器在 2.0 发布后保留 6 个月，届时从 Registry 移除

**次版本升级（如 1.0 → 1.1）**：
- StateVector 在末尾追加新维度（旧维度顺序不变——这是铁律）
- 旧适配器：新维度自动填充为默认值 → 可用但不利用新信息
- 新适配器：可选实现新维度的赋值逻辑

**修订号升级（如 1.0.0 → 1.0.1）**：
- 协议不变，适配器无需任何修改

---

## 五、适配器的兼容性标记

每个适配器必须声明三个元信息：

```python
class MyAdapter:
    ADAPTER_VERSION: str = "1.2.0"
    COMPATIBLE_KERNEL_VERSIONS: str = ">=1.0.0, <2.0.0"  # PEP 440

    # 能力标记：声明这个适配器支持什么
    capability_flags: Set[str] = {"basic", "social_nav", "rl_trained"}
    # basic       = 基础控制（所有适配器必须有）
    # social_nav  = 社交导航（P1/P7 门可工作）
    # rl_trained  = RL 策略已训练（Policy Slots 可挂载）
```

内核在决策时检查能力标记：
- 缺少 `social_nav` → P1/P7 门使用默认阈值（可能不够精确）
- 缺少 `rl_trained` → 降级到 HardThreshold 规则策略

**核心理念**：适配器降级不是失败——是已知边界的优雅处理。

---

## 六、适配器测试契约

每个适配器实现必须附带 4 类测试：

### 1. 往返测试
```python
def test_roundtrip():
    """input → adapter → kernel → adapter → output，语义不丢失"""
    raw = mock_sensor_reading()
    obs = observer.observe(raw)
    cf = kernel_step(ks, obs.to_state_vector())
    result = actuator.execute(cf)
    assert result.action in VALID_ACTIONS
```

### 2. 版本协商测试
```python
def test_version_negotiation():
    """用标记为旧版本的适配器对接新版本内核，验证降级路径"""
    old_adapter = MyObserver(compat_version="1.0.0")
    new_kernel = KernelProtocol(version="1.1.0")
    # 应该通过——1.1.0 是 MINOR 升级，旧适配器兼容
    result = new_kernel.step(old_adapter.observe(raw))
    assert result.safety_flag != SafetyFlag.RED  # 不崩溃
```

### 3. 延迟预算测试
```python
def test_latency_budget():
    total = observer.observer_latency_ms + 1.7 + actuator.actuation_latency_ms
    assert total < 5.0, f"Total latency {total}ms exceeds 5ms budget"
```

### 4. 能力标记测试
```python
def test_capability_degradation():
    """缺少 social_nav 能力时，内核是否正确降级"""
    adapter = MyObserver(capability_flags={"basic"})  # 无 social_nav
    cf = kernel_step(ks, adapter.observe(social_scene))
    assert cf.params.get("social_distance") == DEFAULT_SOCIAL_DISTANCE
```

---

## 七、当前内核已注册的适配器

| 类型 | 适配器 | 域 | 能力标记 |
|------|--------|-----|---------|
| Observer | `NLTextObserver` | 语义 Agent | `basic` |
| Observer | `MockObserver` | 测试 | 固定输出 |
| Actuator | `NLOutputActuator` | 语义 Agent | `basic` |
| Actuator | `MockActuator` | 测试 | 记录序列 |
| Bus | 见 [12-bus-manufacturing-guide.md](./12-bus-manufacturing-guide.md) | — | — |

---

## 八、贡献新适配器

1. 在 `mainboard/adapters/<domain>/` 下创建适配器文件
2. 实现对应类型的 Protocol + 声明元信息（版本 + 兼容性 + 能力标记）
3. 编写 4 类测试（往返 / 版本协商 / 延迟预算 / 能力标记）
4. 提交 PR → CLA-lite 生效
5. 更新本文档第七节（新增你的适配器条目）

---

## 九、附录：当前协议版本快照（v1.0.0）

```
KERNEL_PROTOCOL_VERSION = "1.0.0"

StateVector: 16 维
  ├── INSTANT × 8  (Observer 写入)
  ├── ODE × 5      (内核演化)
  └── DERIVED × 3  (内核计算)

ControlFrame:
  ├── action: enum (MOVE / YIELD / STOP / OBSERVE / ENGAGE / GENERATE / TOOL / WAIT)
  ├── params: MappingProxyType[str, float]
  ├── safety_flag: enum (GREEN / YELLOW / RED)
  ├── trace_id: str
  └── effective_timestamp: float

RouteSignals:
  └── 8 门 × (upper_threshold, lower_threshold, current_value)

兼容窗口: >=1.0.0, <2.0.0
下一个主版本 (2.0.0): RL Policy Slots 默认挂载 + StateVector 可能扩展至 20 维
```

---

> 本文档采用 CC BY-SA 4.0 许可。署名：李政远（FRUNHSAN）。  
> 完整体验路径：[11-migration-guide.md](./11-migration-guide.md) 拆 → [12-bus-manufacturing-guide.md](./12-bus-manufacturing-guide.md) 接 → **本文档** 翻译+存活
