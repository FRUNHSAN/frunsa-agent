# 11 — 内核移植手术手册

**定位**：面向想把 MPC 微内核从本项目中拆出来、装进自己系统的开发者。  
**适用场景**：课题组协作者说"我只要你的决策层"、开源社区说"我有个机器人项目想试试你的微内核"、面试官问"我把它放进我们的机器人要改多少"。

> 姐妹文档：[01-onboarding-for-collaborators.md](./01-onboarding-for-collaborators.md) — "内核在哪、怎么读"

---

## 一、内核边界：精确的文件清单

### 必须移植（内核本体 5 个 + 协议层 4 个 = 9 个文件）

```
mpc_kernel/
├── kernel.py              ← 9 步决策链，纯函数入口
├── ode_integrator.py      ← ODE 连续状态演化
├── route_controller.py    ← 8 门优先级路由（Schmitt 触发器）
├── safety_arbiter.py      ← Hoyer + Lipschitz 安全仲裁 + 三层降级
└── slots/
    └── policy_slots.py    ← Boundary / Cost / Value 三个 RL 策略槽位

protocol/
├── v9_types.py        ← StateVector(16) 定义
├── kernel_state.py        ← KernelState 定义
├── control_frame.py       ← ControlFrame 输出类型
└── route_signals.py       ← RouteSignals 类型
```

### 可选移植（如果要完整事件系统）

```
mainboard/bus/
├── event.py                ← EventBus Protocol（中断脉冲 + Lamport 时钟）
├── tool.py                 ← ToolBus Protocol（APB 外设总线，Semaphore 限流）
├── llm.py                  ← LLMBus Protocol（AHB 高速总线，语义规划调用）
└── telemetry.py            ← TelemetryBus (s,a,r) 记录（CoreSight 调试级）
```

### 明确排除（内核不需要的旧代码——V8 历史层）

```
❌ core/          ← V8 旧内核，已被 V9 mpc_kernel/ 替代
❌ engines/       ← V8 引擎层，已被 MPC 内核替代
❌ components/    ← V8 组件，与微内核无关
❌ rag/           ← RAG 子系统，微内核不涉及
❌ demo/          ← 可视化 demo
❌ tests/conformance/ ← V8 旧测试
❌ .ai_reasoning/ ← 推理链——知识资产，但内核运行时不需要
```

> **内核 + 协议层 = 你唯一需要移植的最小集合。2 个目录，9 个文件，~2500 行代码。**

---

## 二、依赖关系图

```
协议层 (protocol/)           ← 零外部依赖，纯类型定义
    ↑
    │ 内核只 import protocol/ — 不 import mainboard/
    │
内核层 (mpc_kernel/)         ← 纯函数，只依赖 protocol/
    ↑
    │ 总线 import protocol/ + mpc_kernel/
    │
总线层 (mainboard/bus/)      ← 可选——最小移植不需要
    ↑
    │ 你的代码只依赖接口，不修改内核内部
    │
你的代码
    ├── Observer 实现（传感器 → StateVector）
    ├── Actuator 实现（ControlFrame → 执行指令）
    └── 总线实现（如果需要事件系统）
```

**依赖方向是单向的**——内核不依赖 Observer、不依赖 Actuator、不依赖任何总线实现。它是纯函数：传入 StateVector，传出 ControlFrame。

---

## 三、8 步移植步骤

### Step 1：创建目标项目目录

```bash
mkdir my-robot-controller
cd my-robot-controller
mkdir protocol mpc_kernel mpc_kernel/slots
```

### Step 2：复制 protocol/（4 个文件）

```bash
cp /path/to/godot-qwen-agent/protocol/v9_types.py protocol/
cp /path/to/godot-qwen-agent/protocol/kernel_state.py protocol/
cp /path/to/godot-qwen-agent/protocol/control_frame.py protocol/
cp /path/to/godot-qwen-agent/protocol/route_signals.py protocol/
```

### Step 3：复制 mpc_kernel/（5 个文件 + slots/）

```bash
cp /path/to/godot-qwen-agent/mpc_kernel/kernel.py mpc_kernel/
cp /path/to/godot-qwen-agent/mpc_kernel/ode_integrator.py mpc_kernel/
cp /path/to/godot-qwen-agent/mpc_kernel/route_controller.py mpc_kernel/
cp /path/to/godot-qwen-agent/mpc_kernel/safety_arbiter.py mpc_kernel/
cp /path/to/godot-qwen-agent/mpc_kernel/slots/policy_slots.py mpc_kernel/slots/
```

### Step 4：安装依赖

```bash
pip install numpy
# 就这一个。无 PyTorch，无 ROS，无 CUDA。
```

### Step 5：运行内核自检

```python
# test_kernel.py
from protocol.state_vector import StateVector
from protocol.kernel_state import KernelState
from mpc_kernel.kernel import kernel_step

# 创建初始状态
sv = StateVector.default()
ks = KernelState.initial()

# 调用内核
cf = kernel_step(ks, sv)
print(f"✅ Kernel loaded. Action: {cf.action}, Safety: {cf.safety_flag}")
```

### Step 6：实现你的 Observer

```python
# my_observer.py
from protocol.state_vector import StateVector

class MyObserver:
    """把你的传感器数据翻译成 StateVector"""
    
    def observe(self, camera_rgb, lidar_scan, force_torque) -> StateVector:
        sv = StateVector.default()
        
        # 写 INSTANT 维度（Observer 负责）
        sv.instant_social_distance = self._estimate_social_distance(lidar_scan)
        sv.instant_collision_risk = self._estimate_collision_risk(lidar_scan, force_torque)
        sv.instant_user_attention = self._estimate_attention(camera_rgb)
        
        # 不要写 ODE 维度！ODE 积分器会自动演化它们。
        return sv
```

### Step 7：实现你的 Actuator

```python
# my_actuator.py
from protocol.control_frame import ControlFrame

class MyActuator:
    """把 ControlFrame 翻译成你的执行指令"""
    
    def execute(self, cf: ControlFrame):
        if cf.action == "YIELD":
            self.motors.set_velocity(cf.params["velocity"])
            self.motors.set_heading(cf.params.get("lateral_offset", 0))
        elif cf.action == "EMERGENCY_STOP":
            self.motors.stop()
        elif cf.action == "MOVE":
            self.motors.set_velocity(cf.params["velocity"])
            self.motors.set_trajectory(cf.params.get("trajectory"))
```

### Step 8：启动决策循环

```python
# main_loop.py
from protocol.state_vector import StateVector
from protocol.kernel_state import KernelState
from mpc_kernel.kernel import kernel_step
from my_observer import MyObserver
from my_actuator import MyActuator

observer = MyObserver()
actuator = MyActuator()
ks = KernelState.initial()

while True:
    # 1. 传感器 → 状态
    sv = observer.observe(camera.read(), lidar.read(), ft.read())
    
    # 2. 纯函数决策（内核不感知传感器/执行器）
    cf = kernel_step(ks, sv)
    ks = cf.next_state  # KernelState 由外部持有
    
    # 3. 决策 → 执行
    actuator.execute(cf)
    
    # 4. 循环频率由你的实时时钟控制（~1000Hz）
    sleep(0.001)
```

---

## 四、协议版本管理

### 当前协议版本

StateVector 目前 16 维。字段定义见 `protocol/v9_types.py`。

### 升级规则

1. **只能在末尾追加新维度** — 不删除、不重排已有维度
2. **Observer 实现需显式声明支持的协议版本** — `MyObserver.supported_version = "1.0"`
3. **内核 `__post_init__` 做版本检测** — 维度不匹配直接抛错

### 手动更新步骤

```
1. git pull 上游（我的 repo）获取最新 mpc_kernel/ 和 protocol/
2. 复制新文件到你的项目
3. 检查 protocol/ 中新增/变更的类型字段
4. 如果你的 Observer 用的是旧维度数，补齐新维度为默认值
5. 运行内核自检 → 确认通过
```

---

## 五、Fork 与自定义

### 不修改内核内部的扩展方式（推荐）

| 你想做的事 | 你需要写的 | 你需要改的 |
|-----------|-----------|-----------|
| 新 RL 策略 | 实现 `BoundaryPolicy` Protocol → `MyPolicy.evaluate(state) → float` | 零内核代码变更 |
| 新门（P8, P9） | 实现 `Gate` Protocol → `RouteController` 初始化时追加 | `route_controller.py` 的初始化参数 |
| 新 ODE 维度 | 在 `v9_types.py` 末尾追加字段 → Observer 提供值 | `ode_integrator.py` 按维度数自动适配 |
| 替换仲裁规则 | 实现新的仲裁函数 → 替换 `safety_arbiter.py` 的默认仲裁 | `kernel.py` 的仲裁调用（1 行） |

### 需要改内核内部的非常规操作（警告）

| 操作 | 风险 | 需要同步更新的 |
|------|------|-------------|
| 修改 Lipschitz 上限（0.30 → ?） | 过度反应或反应迟钝 | `safety_arbiter.py` + 铁律 #6 + 所有回归测试的期望值 |
| 修改 `kernel_step` 的 9 步执行顺序 | 步骤间有数据依赖，重排可能断链 | `kernel.py` + `DecisionTrace` 审计逻辑 + 全部测试 |
| 修改 Safety Arbiter 降级矩阵结构 | 仲裁器的三层降级是互斥且完备的 | `safety_arbiter.py` + `ControlFrame` 的 safety_flag 语义 |

---

## 六、常见踩坑

### 坑 1：Observer 修改了 ODE 也在演化的同一维度

**症状**：状态跳跃，仲裁器频繁降级  
**原因**：Observer 写了 `ode_` 前缀的维度（这些由 ODE 积分器演化）  
**解决**：维度分工。Observer 只写 `instant_` 前缀维度。ODE 积分器只写 `ode_` 前缀维度。互不越界。

### 坑 2：每次调用内核后需要保存 KernelState

**症状**：每次决策都像"第一次"  
**原因**：`kernel_step` 是纯函数——不保存状态  
**解决**：`KernelState` 由外部（你的循环）持有。每次 `kernel_step` 传入旧的、接收新的 `cf.next_state`。

### 坑 3：具身场景控制循环频率（1000Hz）远高于决策频率（~100Hz）

**症状**：在两次内核调用之间，电机指令没有更新 → 抖动  
**解决**：`ControlFrame` 参数支持插值。在两个 `kernel_step` 调用之间，用线性/样条插值平滑输出。

### 坑 4：协议版本不匹配

**症状**：内核抛 `ValueError: StateVector dimension mismatch`  
**原因**：上游更新了协议（新增维度），你的 Observer 没有同步  
**解决**：`kernel_step` 入口做 `StateVector` 维度检查。维度不匹配直接抛错，不静默降级。

### 坑 5：总线依赖

**症状**：移植后 import 报错，找不到 `mainboard.bus`  
**原因**：你的内核代码中有残留的总线引用  
**解决**：最小移植不需要总线。`kernel_step` 是纯函数，不依赖 EventBus/LLMBus/ToolBus。如果报 import 错误，检查是否有从 `mainboard/` 的残留 import。

### 坑 6：Observer 感知延迟导致帧率高但决策滞后

**症状**：内核 1.7ms 跑完，但动作还是"慢半拍"  
**原因**：Observer 的感知推理（摄像头→特征）花了 30ms，但你没有标注  
**解决**：Observer 实现标注感知延迟预算 `observer_latency_ms: float`。内核在 `ControlFrame` 中标注 `effective_timestamp = now - latency`，让下游 Action 插值器感知到实际延迟。

---

## 七、最小可运行示例（30 行）

```python
"""最小决策循环 — 不依赖任何外部硬件"""
from protocol.state_vector import StateVector
from protocol.kernel_state import KernelState
from mpc_kernel.kernel import kernel_step

# 1. 创建初始状态
sv = StateVector.default()
ks = KernelState.initial()

# 2. 模拟 5 个决策帧
for t in range(5):
    # 模拟传感器读数变化
    sv.instant_social_distance += 0.1 * (t % 2)  # 交替逼近
    
    # 纯函数决策
    cf = kernel_step(ks, sv)
    ks = cf.next_state
    
    # 输出
    print(f"Frame {t}: action={cf.action}, "
          f"safety={cf.safety_flag}, "
          f"params={cf.params}")
    # Frame 0: action=MOVE, safety=GREEN, params={'velocity': 1.0}
    # Frame 1: action=YIELD, safety=GREEN, params={'velocity': 0.5, 'lateral_offset': 10}
    # Frame 2: action=YIELD, safety=GREEN, params={'velocity': 0.3, 'lateral_offset': 15}
    # Frame 3: action=STOP, safety=YELLOW, params={}
    # Frame 4: action=MOVE, safety=GREEN, params={'velocity': 0.8}
```

> **这就是所有协作者的起点。** 从这 30 行开始，接入你自己的传感器和执行器。

---

## 八、贡献规则（CLA-lite）

向本仓库提交 PR 即表示你同意：
- 你的代码贡献以 Apache 2.0 许可发布
- 你的文档贡献以 CC BY-SA 4.0 许可发布
- 你保证你拥有你贡献的代码/文档的版权，且没有侵犯第三方权利

以上规则等价于一个最简 Contributor License Agreement（CLA-lite）。正式 CLA 文件将在 v1.0 发布前完成。

> 参见：[法律-开源许可与知识产权说明.md](./法律-开源许可与知识产权说明.md) — 完整法律保护策略

---

> 本文档采用 CC BY-SA 4.0 许可。署名：李政远（FRUNHSAN）。  
> 完整体验路径：读完本文 → [01-onboarding-for-collaborators.md](./01-onboarding-for-collaborators.md)（内核在哪、怎么读） → [08-architecture-diagram.md](./08-architecture-diagram.md)（架构图）
