# Sylvan: 端到端自动驾驶虚实融合测试系统

Sylvan 是一个课程项目的软件实现，面向端到端自动驾驶系统的非侵入式虚实融合测试。系统以 CARLA 仿真器为核心，通过 ROS2 实时数据或 JSON 离线回放同步车辆姿态与速度，在虚拟环境中生成前向交通场景，并通过单目或双目相机渲染用于 AEB/FCW 等功能验证的视觉输入。

本项目强调“不修改被测车辆原有 CAN 总线、底层控制器和自动驾驶软件”的实验边界，通过外部车辆状态同步和外部视觉显示/注入方式复现长尾危险场景。

## 项目背景

端到端自动驾驶模型具有明显的黑盒特征，传统模块化测试难以充分覆盖极端危险场景。真实试验场建设和运行成本高，且对突发车辆、行人横穿、极端天气等长尾场景的复现存在安全风险。Sylvan 旨在构建一个低成本、可重复、可控制的 CARLA 虚实融合测试原型，为自动驾驶感知与决策响应验证提供实验平台。

## 主要功能

- 连接 CARLA 服务端并以同步模式运行仿真。
- 支持 CARLA 内置 Town 地图和 OpenDRIVE `.xodr` 地图。
- 支持 ROS2 实时车辆状态桥接。
- 支持 JSON 离线车辆状态回放。
- 支持 ROS yaw 到 CARLA yaw 的偏移校准。
- 支持单目和双目前向 RGB 相机渲染。
- 支持天气切换、环境对象隐藏/恢复和干净场景模式。
- 支持动态交通、静态车辆、交通锥和事故/危险场景管理。
- 支持 HUD 状态显示、键盘快捷键和手动驾驶调试。
- 支持统一清理 CARLA actor、相机、ROS 节点和 Pygame 资源。

## 目录结构

```text
.
├── docs/                       # 项目文档
│   ├── SRS_CN.md               # 中文软件需求规格说明书
│   ├── SRS_EN.md               # 英文软件需求规格说明书
│   ├── SDS_CN.md               # 中文软件设计说明书
│   ├── SDS_EN.md               # 英文软件设计说明书
│   └── Project_Management_and_Economic_Analysis_Report.md
├── scripts/
│   ├── run_sync.py             # 主仿真入口
│   └── run_ros_bridge.py       # 独立 ROS 桥接入口
└── src/
    └── carla_auto_vr/
        ├── app/                # CLI、Simulation 装配、主循环
        ├── bootstrap/          # CARLA / ROS 环境准备
        ├── core/               # CARLA 客户端、同步模式、actor 生命周期
        ├── data_sources/       # ROS、JSON、状态应用、yaw 校准
        ├── sensors/            # 单目/双目相机与图像管线
        ├── traffic/            # 动态交通、静态车辆、交通锥
        ├── accidents/          # 事故场景管理与统计
        ├── ui/                 # Pygame 显示、HUD、输入处理
        ├── vehicle/            # 主车生成与键盘控制
        ├── world/              # 地图、OpenDRIVE、天气、环境层
        └── config/             # 配置、常量、日志
```

## 运行环境

推荐环境：

- Python 3.10
- CARLA 0.9.15
- ROS2
- Pygame
- NumPy
- CARLA Python API egg

可选环境：

- 自定义 ROS2 消息包 `testcarla_interfaces`
- OpenDRIVE `.xodr` 地图文件
- 外部 IMU 或车辆状态发布节点

项目当前没有固定的 `requirements.txt`，依赖主要来自 CARLA、ROS2 和本地 Python 环境。运行前请确保 CARLA Python API 可被导入，或将 CARLA egg 路径放在代码可搜索的位置。项目代码会尝试自动查找常见 CARLA egg 路径。

## 快速开始

### 1. 启动 CARLA

先启动 CARLA 服务端，并确认默认端口 `2000` 可用。

### 2. 使用默认配置运行

```bash
python3 scripts/run_sync.py
```

默认行为：

- 连接 `127.0.0.1:2000`
- 加载 `Town04`
- 默认启用 ROS 数据源
- 默认使用双目相机模式
- 默认启用 CARLA 同步模式

### 3. 指定地图

```bash
python3 scripts/run_sync.py --map Town06
```

使用 OpenDRIVE 地图：

```bash
python3 scripts/run_sync.py --map path/to/map.xodr
```

### 4. 使用 JSON 离线回放

```bash
python3 scripts/run_sync.py --json path/to/vehicle_states.json
```

指定 JSON 文件后，系统会忽略 ROS 数据源，按主循环逐帧读取车辆状态。

### 5. 使用单目相机

```bash
python3 scripts/run_sync.py --mono-camera
```

### 6. 创建干净环境

```bash
python3 scripts/run_sync.py --clean-environment
```

该模式会尝试隐藏建筑、植被、围栏、杆状物和墙体，用于更干净的视觉注入或标定实验。

### 7. 开启调试日志

```bash
python3 scripts/run_sync.py --debug
```

## 常用命令行参数

| 参数 | 说明 |
|---|---|
| `--host` | CARLA 服务器主机，默认 `127.0.0.1` |
| `--port` | CARLA 服务器端口，默认 `2000` |
| `--map` | CARLA Town 地图名或 `.xodr` 文件 |
| `--json` | JSON 回放文件路径；提供后忽略 ROS |
| `--ros` | 启用 ROS 数据源 |
| `--debug` | 开启 DEBUG 日志 |
| `--mono-camera` | 使用单目相机 |
| `--stereo-camera` | 使用双目相机 |
| `--clean-environment` | 移除主要环境对象 |
| `--no-buildings` | 初始隐藏建筑 |
| `--no-vegetation` | 初始隐藏植被 |
| `--no-fences` | 初始隐藏围栏 |
| `--layered-rendering` | 启用分层渲染 |
| `--accidents` | 强制开启事故模拟 |

## 运行时快捷键

| 按键 | 功能 |
|---|---|
| `Esc` | 退出系统 |
| `R` | 切换天气 |
| `K` | 启用/禁用键盘车辆控制 |
| `B` | 切换建筑物显示 |
| `V` | 切换植被显示 |
| `F` | 切换围栏显示 |
| `P` | 切换杆状物显示 |
| `M` | 切换墙体显示 |
| `L` | 输出当前环境层状态 |
| `H` | 隐藏全部主要环境对象 |
| `J` | 显示全部主要环境对象 |
| `C` | 输出当前相机模式信息 |
| `Y` | 重置 yaw 校准 |

## JSON 数据格式

JSON 回放文件根节点应为数组，每个元素表示一帧车辆状态：

```json
[
  {
    "timestamp": 1710000000,
    "rotation": {
      "roll": 0.0,
      "pitch": 0.0,
      "yaw": 0.0
    },
    "velocity": {
      "x": 0.0,
      "y": 0.0,
      "z": 0.0
    }
  }
]
```

说明：

- `rotation.yaw` 使用 ROS yaw 弧度值。
- `velocity.x` 表示前向速度。
- `velocity.y` 表示 ROS 左向速度，应用到 CARLA 时会转换为右向速度。

## ROS2 数据接口

系统优先订阅以下车辆状态话题：

- `/carlatest`
- `carlatest`

系统也会尝试订阅以下备选话题：

- `/vehicle/data`
- `/carla/vehicle_data`
- `/vehicle_data`
- `/data`

消息类型优先使用自定义消息：

- `testcarla_interfaces.msg.Gongjicarla`

如果自定义消息不可用，系统会退回到：

- `std_msgs.msg.Float32MultiArray`

期望字段或数组顺序为：

```text
timestamp, pitch, roll, yaw, vel_x, vel_y, vel_z
```

## 文档

项目文档位于 `docs/`：

- `SRS_CN.md`：中文软件需求规格说明书
- `SRS_EN.md`：英文软件需求规格说明书
- `SDS_CN.md`：中文软件设计说明书
- `SDS_EN.md`：英文软件设计说明书
- `Project_Management_and_Economic_Analysis_Report.md`：项目管理与经济分析报告

## 项目边界

本项目不包含以下内容：

- 多摄像头环视拼接；
- 雷达、激光雷达等多模态传感器融合仿真；
- AR 眼镜显示系统开发；
- 测试车辆 CAN 协议逆向工程；
- 商业化云平台、权限管理和多用户管理；
- 真实车辆控制策略或自动驾驶算法开发。

## 安全说明

本项目用于课程工程实践和研究原型验证。真实车辆实验必须在封闭、安全、可控的场地进行，并配置安全人员。软件系统只提供虚拟场景生成、车辆状态同步和视觉渲染能力，不能替代现场安全管理。

## Git 提交注意事项

仓库已通过 `.gitignore` 忽略 `.DS_Store`、Python 缓存、日志和常见临时文件。提交前建议检查：

```bash
git status --short
```

如果仍看到 `.DS_Store`，请不要将其加入暂存区。
