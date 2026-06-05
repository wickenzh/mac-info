# 二手 Mac 信息检测工具

这是一个基于 PyQt6 的 macOS 信息检测工具，用于查看二手 Mac 的硬盘健康、容量使用情况，以及 MacBook 机型的电池信息。

没有内置电池的机型，例如 Mac mini、iMac、Mac Studio，会只显示 SSD 检测卡片；MacBook 会额外显示电池信息。

## 支持环境

- macOS
- Apple Silicon：M1 / M2 / M3 / M4 等 ARM 处理器
- Intel Mac
- Python 3.9 或更高版本

## 运行前安装依赖

### 1. 安装 Homebrew

如果已经安装过 Homebrew，可以跳过这一步。

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. 安装 smartmontools

用于读取 SSD SMART 健康信息。

```bash
brew install smartmontools
```

### 3. 安装 Python 依赖

进入项目目录：

```bash
cd /Users/zhwickner/Documents/Codex/2026-05-21/mac-info
```

安装 PyQt6：

```bash
python3 -m pip install -r requirements.txt
```

如果系统提示没有 `pip`，先运行：

```bash
python3 -m ensurepip --upgrade
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

## 运行工具

在项目目录执行：

```bash
python3 ssd.py
```

## 可检测内容

### SSD 信息

- 硬盘容量和已用空间
- SSD 型号
- SMART 健康状态
- 温度
- 寿命损耗
- 总读取量
- 总写入量
- 总负载时间
- 异常断电次数
- 数据错误次数

### 电池信息

仅 MacBook 等有内置电池的机型显示：

- 制造商
- 制造日期
- 电池年龄
- 循环次数
- 电池序列号
- 电池温度
- 电源适配器连接状态
- 容量健康度
- 当前电量

## 常见问题

### 没有显示 SSD SMART 详细信息

请确认已经安装 smartmontools：

```bash
which smartctl
smartctl --version
```

如果工具仍然提示无法读取，可能是当前机器或系统权限限制了 SMART 信息访问。容量信息仍会正常显示。

### Mac mini 显示无电池是否正常

正常。Mac mini、iMac、Mac Studio 没有内置电池，工具会自动隐藏电池卡片，只检测硬盘。

### 程序直接崩溃怎么办

同目录下会生成崩溃日志：

```bash
cat mac_info_crash.log
```

把日志内容发给开发者即可定位问题。

## 一键安装并运行

已经安装 Homebrew 的情况下，可以直接执行：

```bash
cd /Users/zhwickner/Documents/Codex/2026-05-21/mac-info
brew install smartmontools
python3 -m pip install -r requirements.txt
python3 ssd.py
```
