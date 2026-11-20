# 当前完整版本与新聊天交接

## 项目与唯一基线

- 工作目录：任意克隆位置；脚本以自身位置推导仓库根目录。
- 主线：csRNA + gem5 Timing RNIC 的 RoCEv2 仿真环境。
- 上游提交：`5270d51c584055fb21f05602d624c2bcfb4184c7`。
- 当前只保留 csRNA；JingZhao、旧实验、旧阶段快照和废弃补丁已清理。
- 最新完整交付为 **DCQCN 时间＋字节双触发恢复配置（BR01—BR08）**。这是独立可选配置；冻结的时间触发 DCQCN 仍为默认。双交换机 MS01—MS10、RX01—RX10 及此前能力均包含在当前版本中。

## 已完成能力

- 双栈 RC、保护、队列、Timing DMA、多包、重传、Atomic、Type 2B MW。
- 四 RNIC、单 EtherSwitch、有限缓冲和端口队列。
- ECN/CNP、HPCC/Mellanox 所选配置 DCQCN 和真实出口 pacing，D01—D10 通过。
- 真实 PFC MAC Control、优先级调度、headroom 和 DCQCN 协同，P01—P10 通过。
- 有限 RNIC RX、零拷贝 payload、最后引用 lease 释放、DMA 压力驱动自动 Xoff/刷新/Xon，RX01—RX10 通过并保持冻结。
- 双交换机静态转发、逐跳 PFC、链路在途计账、两类独立压力源、优先级共享路径、接收角色/Reset、CE 跨跳保持和 DCQCN 协同，MS01—MS10 通过。
- 可选 DCQCN 时间＋字节双触发恢复、真实发送计账、T/BC 独立阶段、降速重置、QP 生命周期及 PFC/pacing 协同，BR01—BR08 通过；默认配置保持时间触发。
- 最新 E10 既有回归为 144 项 PASS；它仍包含在 ECN 基线的 167 项不同 PASS 中，不重复累加。
- 未覆盖：超过两台交换机的任意拓扑、标准 verbs 接入、独立实现互操作及文档列出的其他边界。

## 最新交付对应关系

- 完整源码补丁：`patches/csrna-rocev2-protection.patch`
- 当前回归二进制：`model/csrna/build/X86/gem5.opt`
- RX 冻结干净快照：`results/rx-rebuild/csrna/`
- RX 冻结快照二进制：`results/rx-rebuild/csrna/build/X86/gem5.opt`
- 二进制/补丁 SHA-256、30 文件恢复和运行验证：`results/rx-validation.txt`
- 最新验收：`results/br-all.log`
- 最新时间线/汇总：`results/br-timeseries.csv`、`results/br-summary.csv`
- 最新干净快照：`results/br-rebuild/csrna/`
- 最新恢复验证：`results/br-validation.txt`
- MS 验收：`results/mspfc-all.log`
- MS 时间线/汇总：`results/mspfc-joint-timeseries.csv`、`results/mspfc-summary.csv`
- MS 干净快照与验证：`results/mspfc-rebuild/csrna/`、`results/mspfc-validation.txt`
- RX 冻结验收：`results/rx-all.log`
- 既有回归：`results/ecn-e10-check.log`
- RX 时间线/汇总：`results/rx-joint-timeseries.csv`、`results/rx-summary.csv`
- PFC 四模式：`results/pfc-four-modes.csv`、`results/pfc-joint-timeseries.csv`
- DCQCN 对照：`results/dcqcn-d08-summary.csv`

源码工作区中的修改和未跟踪头文件是有意的当前交付内容；完整补丁已经过反向匹配、干净恢复、构建和实际运行检查，不要把它们当作误改清理。

## 保留目录说明

`results/` 中保留的 D/P/RX/MS/BR、ECN、protect/fault/rc-state/qp/mw/ipv6/switch 目录是当前检查器的输入证据，不是旧版本。旧 ECN/DCQCN/PFC 快照已删除，保留冻结的 `rx-rebuild`、已完成的 `mspfc-rebuild` 和当前 `br-rebuild`。重复顶层日志、调试实验和临时二进制已清理。

## 不重跑仿真的快速验证

```bash
cd <克隆目录>
python3 analysis/check_dcqcn.py
python3 analysis/check_pfc.py
python3 analysis/check_rx.py
python3 analysis/check_mspfc.py
python3 analysis/check_br.py
python3 analysis/check_ecn.py e10
sha256sum -c env/checksums.sha256
```

`results/ecn-e10-check.log` 应为 144 行且每行以 PASS 开头；`results/rx-all.log`、`results/pfc-all.log`、`results/mspfc-all.log` 各应为 10 行 PASS，`results/br-all.log` 应为 8 行 PASS；`results/dcqcn-all.log` 覆盖 D01—D10。

## 完整重跑

```bash
JOBS=16 ./scripts/build_model.sh
./scripts/run_dcqcn.sh all
./scripts/run_pfc.sh all
./scripts/run_rx.sh all
./scripts/run_mspfc.sh all
./scripts/run_br.sh all
```

这些是长时间仿真任务，不需要在新聊天开始时重复；只有修改对应功能或证据缺失时才重跑。

## 后续方向

后续可转向标准 verbs 接入或独立实现互操作，保持默认时间触发 DCQCN、可选 BR 配置、RX 自动 PFC 语义和双交换机基线不变。各阶段证据分开登记，不以可选 BR 配置改写旧默认验收口径。

新聊天建议首先阅读本文件和 `docs/baseline_acceptance.md`，然后明确要修改的当前模块，不需要重新盘点旧历史。
