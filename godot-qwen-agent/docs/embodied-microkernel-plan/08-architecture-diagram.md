# 08 — 架构图、比喻体系与时序预算

**定位**：统一所有文档和面试中的表述。包含三个核心物料：大脑-小脑-脊髓比喻 + ROS2 集成拓扑 + 9 步时序预算表。

> 参见：[../ARCHITECTURE.md](../ARCHITECTURE.md) — 五层架构速查  
> 参见：[01-onboarding-for-collaborators.md](./01-onboarding-for-collaborators.md) — 各层文件导读

---

## 一、核心比喻：大脑 - 小脑 - 脊髓

这个比喻用于面试/套磁时让非技术面试官（HR/教授）在 30 秒内理解你的项目位置：

```
多模态大模型 (VLA / Agent / LeRobot)
  │  "大脑" — 看得远，懂战略（语言/视觉/规划）
  │  运行在 GPU 云，输出 10-30Hz 的高层语义指令
  │  问题：反应慢（100-300ms），缺乏物理常识
  │
  ▼  "把咖啡端过来" / "跟着这位老人走"
══════════════════════════════════════════════════════════
  🌟 你的微内核 (Embodied Microkernel) 🌟
  │  "小脑 + 脑干" — 懂物理，能实时纠错
  │
  │  RL 策略网络：泛化与适应（"没见过的走廊也能走"）
  │  MPC 求解器：物理约束与安全兜底（"不能撞墙、不能摔倒"）
  │  连续→离散映射：状态估计 + 阻抗滤波
  │
  │  输出 500-1000Hz 的安全关节力矩/位置/速度指令
  ▼  "减速至 0.3m/s，偏右 15°，保持社交距离 1.2m"
══════════════════════════════════════════════════════════
  ROS2 / ros2_control
  │  "脊髓" — 执行力极强（1000Hz），但无变通能力
  │  Hardware Interface 直接驱动电机/减速器/传感器
  │
  ▼
[电机] [减速器] [力传感器] [IMU]
```

**比喻对照表**：

| 层 | 人体比喻 | 公司比喻 | 频率 | 决策特性 |
|----|---------|---------|------|---------|
| 多模态大模型 | 大脑皮层 | CEO | 10-30Hz | 战略、语义、远期规划 |
| **你的微内核** | **小脑+脑干** | **中层战术总监** | **500-1000Hz** | **物理约束、实时纠错、安全兜底** |
| ROS2/Hardware | 脊髓 | 基层工人 | 1000Hz+ | 执行、反馈、无变通 |

---

## 二、五层架构 ASCII 图

```
Layer 5: UI ── CLI / VSCode / Web (任意载体)
    │ user_text / sensor_raw
    ▼
Layer 4: Observer ── 语义翻译 (自然语言 → ObservationResult)
    │ obs ── [observer/observer.py]
    ▼
Layer 3: Mainboard ── 主板 (总线矩阵 + 编排层 + 插件系统)
    │                 [mainboard/orchestrate/harness.py]
    │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐
    │  │ LLM Bus  │ │ Tool Bus │ │Event Bus │ │Telemetry Bus│
    │  │ (AHB级)  │ │ (APB级)  │ │ (NVIC级) │ │(CoreSight)  │
    │  └──────────┘ └──────────┘ └──────────┘ └─────────────┘
    │  KernelInput                          ControlFrame
    ▼
Layer 2: MPC Kernel ── 纯函数决策 (零自然语言)
    │  [mpc_kernel/kernel.py] kernel_step() — 9 步（Step 0-8）:
    │    0.NaN入口 → 1.ODE积分 → 2.交互基 → 3.Lipschitz裁剪
    │    → 4.Streak+Pre-exit+8门路由 → 5.连续控制量
    │    → 6.安全仲裁器 → 7.NaN出口 → 8.组装输出
    │  ControlFrame (next_action + data_policy + trace)
    ▼
Layer 1: Execution ── LLM Synthesis / Tool Execution / Track C
```

---

## 三、四条总线

| 总线 | 对标硬件 | 方向 | 职责 | 具身域映射 |
|------|---------|------|------|-----------|
| **LLM Bus** | AHB (高速总线) | 双向 | LLM 调用：地址解码 + 协议翻译 + MAC 重试 | 语义规划 → 大模型推理 |
| **Tool Bus** | APB (外设总线) | 双向 | 工具调用：Semaphore(5) 限流 + 超时 | 抓取/导航工具调用 |
| **Event Bus** | NVIC (中断控制器) | 外设→内核 | 中断脉冲：优先级仲裁 + Lamport 时钟 | 碰撞预警 / 紧急停止 |
| **Telemetry Bus** | CoreSight (调试) | 单向出 | (s,a,r) 三元组 → JSONL 异步写入 | RL 训练数据采集 |

---

## 四、ROS2 集成拓扑

你的内核不作为普通 ROS2 Node 订阅/发布 Topic——那样 DDS 的毫秒级抖动会让 1000Hz 控制环路崩溃。  
**正确做法**：作为 `ros2_control` 框架的 Custom Controller 插件，在进程内与 Hardware Interface 共享内存。

```
┌─ 非实时域（Linux, GPU）─────────────┐
│  多模态大模型 / LeRobot               │
│  输出：目标位姿 / 语义动作 / 粗略轨迹  │  ~10-30Hz
└──────────┬──────────────────────────┘
           │ ROS2 Topic (低频，语义级)
           ▼
┌─ 实时域（RT-Linux / MCU）───────────┐
│                                       │
│  ┌─ ros2_control ──────────────────┐ │
│  │  Controller Manager              │ │
│  │    │                             │ │
│  │    ├─ Custom Controller          │ │
│  │    │   🌟 你的微内核在这里 🌟     │ │
│  │    │   kernel_step() 纯函数调用   │ │  ~500-1000Hz
│  │    │   共享内存，不过 DDS          │ │
│  │    │                             │ │
│  │    └─ Hardware Interface ────────┘ │  ~1000Hz
│  │         │                           │
│  └─────────┼───────────────────────────┘
│            │ 电机指令
│            ▼
│  [电机驱动器] [减速器] [编码器]
└───────────────────────────────────────┘
```

> **关键数字**：绕过 DDS 后，控制环路延迟 < 1ms。纯函数内核本身 ~1.7ms。  
> 加上 Observer 感知推理（摄像头→StateVector），总额算 < 5ms。

---

## 五、9 步内核 Pipeline 逐步骤时间预算（Step 0-8）

```
kernel_step(KernelInput) → ControlFrame
─────────────────────────────────────────────────

Step 0: NaN入口扫描 + Lamport 时钟排序  → ~0.1ms
  │  过滤非法浮点数，按因果序排列事件
  ▼
Step 1: ODE 连续状态演化              → ~0.5ms
  │  脉冲响应 + EMA 弛豫 (1-exp(-dt/τ))
  │  帧率无关——不依赖调用间隔
  ▼
Step 2: 交互基计算                    → ~0.1ms
  │  从 StateVector 提取交互特征基
  ▼
Step 3: Lipschitz 梯度约束 + 双传感器融合  → ~0.1ms
  │  ‖Δs‖ ≤ 0.30 — 防止过度反应
  │  drift ⊕ clarity 融合
  ▼
Step 4: Streak 计数 + 门预退出        → ~0.3ms
  │  连续同类事件累积 → 提前触发
  ▼
Step 5: 连续控制量（DataPolicy）           → ~0.1ms
  │  计算 verbosity_budget, tone_vector, safety_threshold
  ▼
Step 6: 安全仲裁器                    → ~0.3ms
  │  Hoyer 稀疏度 (结构判别) + Lipschitz 约束
  │  三层降级矩阵
  ▼
Step 7: NaN 出口扫描                  → ~0.1ms
  │  确保输出帧不含非法值
  ▼
Step 8: ControlFrame 组装             → ~0.1ms
  │  { action, params, safety_flag, trace_id }
─────────────────────────────────────────────────
Total (纯 Python，未优化):            ~1.7ms
目标 (含 Observer 感知推理 ~3ms):     < 5ms
```

**对比人类反应时间（~200ms），快 40 倍以上。**

---

## 六、双域部署：语义 Agent vs 具身智能

同一内核，不同 Observer + 总线实现：

| 维度 | 语义 Agent 域 | 具身智能域 |
|------|-------------|----------|
| **Observer** | NL 文本解析 → 情感/意图/信息需求特征 | 多模态传感器融合 → 物理状态特征 |
| **StateVector 填充** | 情感维度 + 认知维度 | 位姿维度 + 力觉维度 + 社交维度 |
| **LLM Bus** | 文本生成请求 | 高层语义规划请求 |
| **Tool Bus** | API 调用 / 知识检索 | 抓取/导航原语调用 |
| **Event Bus** | 用户输入中断 | 碰撞预警 / 紧急停止 |
| **Telemetry Bus** | (intent, response, feedback) | (state, action, reward) → RL 训练数据 |
| **动作空间** | GENERATE / TOOL / WAIT / CLARIFY | MOVE / YIELD / STOP / OBSERVE / ENGAGE |
| **控制频率** | 秒级（对话轮次） | 毫秒级（1000Hz 控制回路） |

**内核代码零改动。** 这是铁律 #3（零自然语言 I/O）的直接工程后果——16 个 float 不关心它们来自对话文本还是激光雷达。

> 参见：[11-migration-guide.md](./11-migration-guide.md) — 如何把内核移植到你的系统

---

## 七、八门优先级路由（P0-P7）

```
优先级从高到低：
P0: EMERGENCY_STOP    — 碰撞即将发生 / 力传感器超限
P1: SOCIAL_INTRUSION  — 社交距离入侵（< 0.8m）
P2: PATH_DEVIATION    — 路径偏离（偏离规划轨迹 > 0.3m）
P3: VELOCITY_MISMATCH — 速度不匹配（周围人加速/减速）
P4: UNCERTAINTY_HIGH  — 状态不确定性高（传感器噪声大）
P5: EXPLORE_BIAS      — 探索偏置（RL 探索 vs 利用）
P6: TASK_PRIORITY     — 任务优先级切换
P7: SOCIAL_NORM       — 社交规范违反（逆行 / 挡路）

> **注**：以上为具身域的目标映射。当前代码 `route_controller.py` 中的 gate_id 为语义 Agent 域命名（P0_SOCIAL / P1_TRUST_CRISIS / P2_META_ESCALATED / P3_META_RELAXED / P4_COLD_START / P5_ERROR_STREAK_UP / P6_ERROR_STREAK_DOWN / P7_VARIANCE_CRISIS）。具身域的实现需替换门函数但保留 Gate Protocol 接口不变。
```

**Schmitt 触发器机制**：每个门有两个阈值（上阈值触发，下阈值复位），防止在阈值边界振荡。这是 V6 的工程选择——HardTanh 死区 + 迟滞，替代 Sigmoid 的渐近残差。

---

## 八、关键的"一句话图"（面试白板用）

面试白板时，画这张图 + 标注三个数字，30 秒搞定：

```
大模型 ──→ [你的微内核] ──→ ROS2
10-30Hz      500-1000Hz      1000Hz
战略层        战术层           执行层
"拿咖啡"      "怎么拿"         "动"
              ←1.7ms→
              纯函数
              零自然语言
```

然后补充一句："从传感器读数到安全动作输出，全程 < 5ms。比人类反应快 40 倍。内核 9 个文件，~2500 行纯 Python，零自然语言——驱动对话 Agent 和驱动机器人是同一套代码。"

---

> 本文档采用 CC BY-SA 4.0 许可。署名：李政远（FRUNHSAN）。
