# 12 — 总线制造指南：内核怎么接上你的通信层

**定位**：面向想把内核接入特定通信协议/中间件的开发者。  
**前提**：你已经完成 [11-migration-guide.md](./11-migration-guide.md) 的 8 步移植——内核能在你的项目里跑纯函数循环了。下一步是接通信。

> 姐妹文档：[11-migration-guide.md](./11-migration-guide.md) — "内核怎么拆出来"  
> 下游文档：[13-adapter-kernel-version-protocol.md](./13-adapter-kernel-version-protocol.md) — "数据怎么翻译 + 版本怎么兼容"

---

## 一、总线模型速览

V9 内核定义了四条总线，对标 ARM 硬件总线架构。内核不感知总线的具体实现——只调用 Protocol 定义的方法签名。

| 总线 | 硬件对标 | 方向 | Protocol 签名 | 当前实现 |
|------|---------|------|--------------|---------|
| **EventBus** | NVIC（中断控制器） | 外设→内核 | `emit(event) → None` / `drain() → list[KernelEvent]` | `mainboard/bus/event.py` |
| **LLMBus** | AHB（高速总线） | 双向 | `request(prompt, policy) → BusResponse` | `mainboard/bus/llm.py` |
| **ToolBus** | APB（外设总线） | 双向 | `execute(tool_call, policy) → ToolResult` | `mainboard/bus/tool.py` |
| **TelemetryBus** | CoreSight（调试） | 单向出 | `record(state, action, reward) → None` | `mainboard/bus/telemetry.py` |

**核心规则**：实现一条新总线 = 实现对应的 Protocol + 注册到 Mainboard。内核代码零改动。

---

## 二、总线实现的最小契约

每个总线实现必须：

1. **实现 Protocol 的全部方法签名**（参数名、返回类型一致）
2. **声明 `bus_latency_ms: float`** — 该总线的预期延迟（用于内核的时序预算计算）
3. **注册到 Mainboard** — `Mainboard.register_bus(bus_type, implementation)`

---

## 三、按域分：常见目标系统的实现指南

### 域 1：ROS2（具身智能 / 机器人）

```
EventBus → ROS2 Publisher ("/kernel/events")
  ├── 事件类型 → topic 名称映射
  ├── 优先级 → QoS（高优=RELIABLE+TRANSIENT_LOCAL，低优=BEST_EFFORT）
  └── Lamport 时钟 → Header.stamp

ToolBus → ROS2 Action Server
  ├── grasp → /tools/grasp (Action)
  ├── navigate → /tools/navigate (Action)
  └── 超时 → Action cancel

LLMBus → ROS2 Service Client
  ├── query_vla → /vla/query (Service) — 调用多模态大模型
  └── 超时 → Service call timeout → 降级到本地规则引擎

TelemetryBus → rosbag2 Writer
  ├── (s,a,r) → /telemetry topic → rosbag2 record
  └── 脱敏后用于 RL 训练
```

> **关键**：ROS2 的 DDS 抖动（5-50ms）不满足 1000Hz 控制回路。  
> EventBus 和 ToolBus 映射到 ROS2 topic 用于**低频事件**（碰撞预警 ~100Hz 即可）。  
> 高频控制（1000Hz）走共享内存——见域 2。

### 域 2：纯共享内存 / RT（实时控制）

```
EventBus → 环形缓冲区 + 信号量 (lock-free SPSC queue)
  ├── 每个事件 64 bytes 固定大小（cache line 友好）
  ├── 优先级仲裁在写入端完成
  └── 延迟 < 1μs

ToolBus → 共享内存命令队列
  ├── 命令 = {opcode: u8, params: [f32; 7]}
  └── 无动态分配——编译期固定大小

LLMBus → N/A（实时域没有大模型推理）
  └── 通过 ControlFrame.safety_flag 降级时自动跳过 LLMBus

TelemetryBus → 环形缓冲区 trace（异步 flush 到磁盘）
  ├── 每个 trace entry = 128 bytes
  └── 写满时覆盖最旧条目（不阻塞）
```

### 域 3：HTTP / WebSocket（云端 Agent）

```
EventBus → WebSocket push (JSON)
  ├── 每个事件 → {"type": "...", "priority": ..., "lamport_ts": ...}
  └── 客户端 WebSocket 连接断线 → 缓冲 32 个事件，重连后 drain

ToolBus → HTTP POST /tools/{name}
  ├── Request: {"params": {...}, "data_policy": {...}}
  └── Response: {"result": ..., "contract_violation": null}

LLMBus → HTTP POST /v1/chat/completions (OpenAI-compatible)
  ├── 已实现：mainboard/bus/llm.py（httpx + MAC 重试）
  └── 零第三方 SDK——只依赖 httpx

TelemetryBus → 异步 JSONL write
  └── 每行一条 (s,a,r)，批量 flush（100ms interval）
```

### 域 4：MQTT / LCM（轻量 IoT / 无人机）

```
EventBus → MQTT publish ("drone/sensors/events")
  ├── QoS 1（至少一次送达）
  └── retain = false（事件不需要保留）

ToolBus → MQTT request/reply ("drone/tools/...")
  └── 30s timeout → 降级到预设动作

LLMBus → N/A 或 LCM 桥接（如果地面站有 GPU）

TelemetryBus → MQTT retain ("drone/logs/telemetry")
  └── 最后一条消息保留（地面站重连时可回溯最新状态）
```

---

## 四、从零实现一条总线（以 ROS2 EventBus 为例）

### Step 1：读 Protocol 签名

```python
# mainboard/bus/event.py 的 Protocol（简化）：
class EventBusProtocol:
    def emit(self, event: KernelEvent) -> None: ...
    def drain(self) -> list[KernelEvent]: ...
```

### Step 2：写 ROS2 publisher wrapper

```python
# my_ros2_event_bus.py
import rclpy
from std_msgs.msg import String
import json
from mainboard.bus.event import EventBusProtocol

class ROS2EventBus(EventBusProtocol):
    bus_latency_ms = 5.0  # DDS 预期延迟
    
    def __init__(self, node):
        self.publisher = node.create_publisher(String, '/kernel/events', 10)
        self._buffer = []
    
    def emit(self, event):
        self._buffer.append(event)
        msg = String()
        msg.data = json.dumps({'type': event.type, 'priority': event.priority})
        self.publisher.publish(msg)
    
    def drain(self):
        events = self._buffer.copy()
        self._buffer.clear()
        return events
```

### Step 3：实现优先级仲裁（映射到 ROS2 QoS）

```python
# 高优事件 → RELIABLE + TRANSIENT_LOCAL（保证送达）
# 低优事件 → BEST_EFFORT（丢几帧没事）
```

### Step 4：Lamport 时钟 → ROS2 Header.stamp

```python
msg.header.stamp = node.get_clock().now().to_msg()
# Lamport 时间戳作为逻辑时钟嵌入消息体
msg.lamport_ts = event.lamport_ts
```

### Step 5：注册到 Mainboard

```python
from mainboard.orchestrate.harness import Mainboard
mainboard = Mainboard()
mainboard.register_bus('event', ROS2EventBus(node))
```

### Step 6：测试

```python
# 注入假中断脉冲
bus.emit(KernelEvent(type='collision_warning', priority=0))
# 检查 topic 是否有消息
# ros2 topic echo /kernel/events
```

---

## 五、总线与内核的时序约定

| 总线 | 预期延迟 | 超时行为 |
|------|---------|---------|
| EventBus | < 0.5ms（中断级，共享内存） | 超时 = 本帧跳过该中断 → 下帧 drain 时合并处理 |
| LLMBus | < 300ms（大模型推理） | 超时 = 降级到本地规则引擎 / 默认策略 |
| ToolBus | < 50ms（API 调用 / 运动规划） | 超时 = 反馈 contract_violation → 内核触发降级 |
| TelemetryBus | 异步，无延迟要求 | 写满环形缓冲区 → 覆盖旧数据（不阻塞内核） |

内核不感知总线的具体延迟——总线实现必须自行标注 `bus_latency_ms`，并在超时时执行降级逻辑。内核只消费总线返回的 `BusResponse` 或 `ToolResult`。

---

## 六、贡献新总线实现

1. 放在 `mainboard/bus/implementations/<domain>/` 下
2. 附带 `README.md`：目标协议、延迟约定、测试方法
3. 实现对应 Protocol，标注 `bus_latency_ms`
4. 提交 PR → CLA-lite 自动生效
5. 社区贡献总线模板见 `mainboard/bus/implementations/_template/`

---

> 本文档采用 CC BY-SA 4.0 许可。署名：李政远（FRUNHSAN）。  
> 完整体验路径：读完本文 → [13-adapter-kernel-version-protocol.md](./13-adapter-kernel-version-protocol.md)（数据怎么翻译 + 版本怎么兼容）
