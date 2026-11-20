# RoCE RC 仿真环境运行说明

## 当前主模型与位置

默认且仅保留 csRNA，固定上游提交为 `5270d51c584055fb21f05602d624c2bcfb4184c7`，gem5 基础版本为 20.1.0.2。

仓库可克隆到任意目录，脚本以自身位置推导根目录；上游源码、gem5 构建树和实验结果均生成在仓库内。首次运行 `./scripts/setup.sh` 获取固定上游提交并应用补丁，无需兼容符号链接。

本地适配包括：

- `patches/csrna-rocev2-protection.patch`：当前完整 csRNA 交付，覆盖双栈 RoCEv2、RC/MW、交换、ECN/CNP、DCQCN、PFC、有限 RX、自动流控与双交换机逐跳传播；包含 `rocev2.hh`、`dcqcn.hh`、`pfc.hh` 和 README 链接。
- `patches/csrna-build-compat.patch`：补齐旧 gem5 工具的执行权限；`scripts/build_model.sh` 同时处理 `README.md` 兼容链接。

## 构建

项目内隔离使用 Python 3.8、SCons 3.1.2 和 six 1.16.0，不需要 Docker 或修改系统 Python。实际编译器为 GCC/G++ 9.4.0，完整版本见 `env/versions.yaml`。

```bash
./scripts/setup.sh
JOBS=16 ./scripts/build_model.sh
```

`env/checksums.sha256` 保存最终二进制、补丁、脚本和独立检查器摘要。修改源码后必须重新构建并更新该文件。

## 正常运行

默认配置为两个 SE 端点、每端一个 RNIC、一个 CPU、1 GiB 模拟内存、TimingSimpleCPU、100 Gbps 以太网链路。

```bash
RUN_ID=my-write ./scripts/run_rc.sh write
RUN_ID=my-read ./scripts/run_rc.sh read
FIXED_WR_NUM=16 RUN_ID=fixed-write ./scripts/run_rc.sh write
FIXED_WR_NUM=16 RUN_ID=fixed-read ./scripts/run_rc.sh read
```

每次运行写入 `results/<run_id>/`，包含完整命令、运行参数、源码状态、本地差异、模拟日志、gem5 配置/统计和 `rocev2.server.pcap`、`rocev2.client1.pcap`。设置 `PACKET_TRACE=0` 可关闭导出。可用 `DEBUG_FLAGS=HanGuRnic,CcuEngine,DmaEngine,MrResc,RdmaEngine` 启用调试日志。

固定请求结果核对：

```bash
python3 analysis/check_fixed_rc.py results/fixed-write-completion results/fixed-read-completion
python3 analysis/check_timing_rc.py results/timing-normal-valid results/timing-high-latency-valid
python3 analysis/check_completion_order.py
```

## 保护、跨页和多包

```bash
MAX_TICKS=150000000000 ./scripts/run_protection.sh all
python3 analysis/check_protection.py results/protect-*
python3 analysis/check_rocev2_pcap.py results/protect-*
```

套件包括错误 key、失效 MR、PD 隔离、权限、范围/溢出、本地 Read 目的区保护、本地读默认允许、双上下文矩阵、跨缓存行、真正跨页和双包 Read/Write。

## QP 状态、标准完成码与 Atomic

```bash
MAX_TICKS=200000000000 ./scripts/run_qp.sh all
python3 analysis/check_qp.py
python3 analysis/check_operations.py results/qp-send results/qp-send-multipacket \
  results/qp-send-imm results/qp-write-imm results/qp-duplicate-send-multipacket
python3 analysis/check_qp_completion.py results/qp-send-batch results/qp-reset-inflight
python3 analysis/check_atomic.py
python3 analysis/check_atomic_ext.py
```

当前已验收 QP 生命周期、SEND/RECV、Immediate、RNR 恢复及耗尽、SQD 排空、Read 额度、Fence、多 SGE、选择性完成和队列回绕。64 位 CAS/FAA 使用 gem5 Timing 原子事务，已验证多 QP 同址原子性、重传只执行一次、首次旧值重放、共享 Read/Atomic 额度及错误/复位路径。

## RC 丢失与重复故障

```bash
MAX_TICKS=150000000000 ./scripts/run_fault.sh all
python3 analysis/check_fault.py results/fault-*
python3 analysis/check_rocev2_pcap.py results/fault-*
```

故障脚本使用 5 us 重传超时，分别覆盖丢 Write/Read 请求、丢 ACK/Read Response、重复 Write/Read 请求和重复 Read Response。正常默认超时为 100 us，可用 `RETRANS_TIMEOUT` 调整。重传复用窗口报文，重复写请求不得重复修改目标内存。

## RC 可靠性扩展

```bash
MAX_TICKS=150000000000 ./scripts/run_rc_state.sh all
python3 analysis/check_rc_state.py \
  results/rc-state-psn-wrap-write results/rc-state-psn-wrap-read \
  results/rc-state-outstanding-write results/rc-state-outstanding-read \
  results/rc-state-out-of-order-write results/rc-state-out-of-order-read \
  results/rc-state-consecutive-ack-loss results/rc-state-retry-exhausted \
  results/rc-state-consecutive-request-loss \
  results/rc-state-multipacket-out-of-order results/rc-state-multipacket-read-middle
```

扩展套件覆盖 24 位 PSN 回绕、一次提交 8 个 outstanding、Sequence Error NAK、连续请求/ACK 丢失、窗口回退、多包恢复、三段 Read Response 和重试耗尽。可用 `INITIAL_PSN=16777214` 设置回绕前的初始序号，用 `RETRANS_LIMIT` 设置恢复次数上限。三段正常 DMA 使用默认 100 us 超时；故障测试使用 5 us 超时。

DMA 背压和延迟对照：

```bash
RUN_ID=retry-cross-line-fixed PROTECT_MODE=12 DMA_RETRY_COUNT=4 DMA_DELAY=1000ps \
  DEBUG_FLAGS=DMA,DmaEngine,RdmaEngine MAX_TICKS=150000000000 ./scripts/run_rc.sh write
RUN_ID=timing-normal-valid MAX_TICKS=150000000000 ./scripts/run_rc.sh write
RUN_ID=timing-high-latency-valid DRAM_TCL=27500ps DRAM_TRCD=27500ps \
  MAX_TICKS=150000000000 ./scripts/run_rc.sh write
python3 analysis/check_retry.py
```

当前最终二进制下默认/高延迟 Write 分别完成 1296/999 次。普通测试按固定仿真时间结束，完成数只用于相同配置下的 Timing 对照，不作为 Read/Write 性能比较。

## RC Type 2B Memory Window

```bash
MAX_TICKS=2000000000000 ./scripts/run_mw.sh all
python3 analysis/check_mw.py
python3 analysis/check_rocev2_pcap.py \
  results/mw-bind results/mw-reject results/mw-rebind results/mw-send-inv \
  results/mw-rnr results/mw-timing results/mw-lifecycle results/mw-reuse
```

MW01—MW08 覆盖 Bind、Read/Write/CAS/FAA、绑定拒绝、本地失效与重绑定、零/多包 SEND_WITH_INV、RNR/重复包、Timing 退休、QP/MR/MW 生命周期、重叠窗口，以及同一 MW 保持 24 位 index 不变时的 8 位 tag 回绕。MW08 使用 `ibv_inc_rkey()`，按 `fe → ff → 00 → 01` 更新 tag，并逐档验证当前 key 可访问、旧 tag 被拒绝。MW06 使用 `ATOMIC_RESPONSE_DELAY=300us` 注入目标完成处理延迟，并要求失效时存在非零旧引用、旧 Atomic 全部退休后才发布失效完成。Bind 和 Local Invalidate 是本地 SQ 操作，不生成网络报文；pcap 主要核对远端访问和 SEND_WITH_INV。

## IPv6 RoCEv2 双栈仿真

```bash
./scripts/run_ipv6.sh all
python3 analysis/check_ipv6.py
python3 analysis/check_rocev2_pcap.py results/ipv6-*
```

`ROCE_IP_VERSION=6` 启用 IPv6，默认值为 4。IPv6 使用 40 字节基本头、静态 `fd00::a/b` 地址映射、UDP 4791 和 ICRC。当前生成有效的非零 UDP 校验和，接收同时接受零值与有效非零值；ICRC 对该字段始终按 `0xffff` 处理。17 个代表场景及独立 pcap 均已通过，传输头检查包括 BTH 与 RETH/AETH/AtomicETH 等；最新汇总见 `results/ecn-e10-check.log`。当前不包含 IPv6 扩展头链、分片、动态邻居发现或混合地址族会话。

## 四端点交换与有限队列

```bash
./scripts/run_switch.sh all
python3 analysis/check_switch.py
```

交换测试使用四个模拟 RNIC 和一台 EtherSwitch，默认 100 Gbps 交换速率、1 MiB 出口缓冲和 10 µs 链路传播时延。可用 `SWITCH_FABRIC_SPEED`、`SWITCH_BUFFER_SIZE` 调整瓶颈；S05 使用 512 B 缓冲触发真实丢弃，S06 使用 10 Mbps 出口验证忙时重试与排空。逐端口统计和队列时间序列保存在各场景的 `simulation.log`，包数与字节数必须满足守恒且最终排空。

## 双栈 ECN/CNP 反馈路径

```bash
./scripts/run_ecn.sh all
python3 analysis/check_ecn.py e01 e02 e03 e04 e05 e06 e07 e08 e09
```

E01–E09 分别覆盖关闭/低负载、码点和阈值、双栈报文完整性、真实反馈、多 QP、Read Response 方向、合并/RESET、RC 资源隔离和 CNP 丢失；E10 自动运行既有固定 Read/Write、Timing、DMA retry、保护、故障、RC、QP、Atomic、MW、IPv6 和 S01–S08 回归。`ECN_THRESHOLD` 控制预计队列字节阈值，`CNP_MERGE_INTERVAL` 控制每 QP 合并间隔。默认报文使用 ECT(0)，CNP 为 opcode `0x81`、PSN 0、16 字节全零 reserved。

ECN/CNP 阶段仅提供源 QP 拥塞通知；CNP 驱动的降速/恢复在下一节单独验收。该阶段结果保存在 `results/ecn-*`，检查摘要为 `results/ecn-e01-e09-check.log` 和 `results/ecn-e10-check.log`。

## DCQCN 发送速率控制与报文调度

```bash
./scripts/run_dcqcn.sh all
python3 analysis/check_dcqcn.py
```

控制器固定参考 [High-Precision-Congestion-Control](https://github.com/alibaba-edu/High-Precision-Congestion-Control) 提交 `9f4be2a9ead8a90e8bf732c66bd758c00e58e5be` 的 Mellanox CX4+ 实现，对应 `rdma-hw.cc` 中 `cnp_received_mlx`、`UpdateAlphaMlx`、`CheckRateDecreaseMlx` 和恢复函数。默认配置与原论文版本不完全相同：只使用时间驱动恢复；可选的时间＋字节双触发配置在后文 BR 阶段单独说明。

- 初始当前/目标速率为 100 Gbps，最小速率 100 Mbps，α=1，AI/HAI 步长为 5/50 Mbps。α 使用双精度浮点和 1/16 增益；速率使用整数 bit/s。
- 首个 CNP 设置 α/降速/恢复状态，启动 55 us α 周期及 4 us+1 ns 降速监测；首个 CNP 的速率倍率默认为 1。后续 CNP 只置位两个到达标志，同一监测周期内多个 CNP 只产生一次降速。
- 降速使用当时的 α：`Rc=max(Rmin,Rc*(1-alpha/2))`。默认在恢复阶段 0 保存原目标速率，其后或显式 clamp 时先把目标速率设为降速前速率。
- 默认五个 Fast Recovery 事件，然后一次 AI，再进入 HAI；恢复周期默认 1500 us。FR 使用当前/目标速率均值，AI/HAI 先提高目标速率再取均值，目标速率不超过最大值。
- RTS 空闲或 SQD 时保留控制状态和定时器；ERR/RESET 删除控制状态、待发报文及本地旧事件。当前自定义 ABI 没有独立 QP destroy 命令，重建前的销毁语义由 ERR/RESET 路径覆盖。

逐包 pacing 位于 `sauProcessing` 真实出口之前。计费长度为完整已建模帧 `packet->length`，间隔为 `ceil(8*L*10^12/R)` tick（1 tick=1 ps），不累积空闲突发；速率改变时按上一包长度调整既有 `nextSend`。只有 `sendPacket` 真正接纳才更新预算、pcap 和统计，busy 不扣预算，RC 重传作为新发送重新计费。RC 超时只在对应报文实际发出后启动，恢复窗口未全部发出时不会被重复排队。

SEND、Write、Read/Atomic 请求、Read/Atomic 响应使用各 QP 的独立 pacing；ACK、NAK、CNP 不被 QP 限速，使用控制优先调度但仍占用交换端口带宽。UD/CM 不属于本轮 DCQCN。接收侧 CNP 合并键为本地 QPN 和实际源 MAC，避免三对一共享本地 QPN 时反馈全部流向同一源。

D01—D10 分别覆盖固定速率与禁用对照、首个 CNP、周期合并、α 与 FR/AI/HAI、变长包/busy/重传、响应端与双向传输、多 QP 确定性、持续三对一、故障与生命周期、IPv6 及既有全量回归。D08 使用 10 Gbps 交换出口、512 B ECN 阈值、每流 100 WR 和最多 8 个 outstanding；对照不预设 DCQCN 必须提高所有性能指标。`results/dcqcn-d08-*/sustained/timeseries.csv` 对齐 CNP、控制状态、实际发包和交换队列，`results/dcqcn-d08-summary.csv` 分别记录实际发送速率与按唯一 PSN 去重的 goodput。

RX 阶段快照保留在 `results/rx-rebuild/`，双交换机快照为 `results/mspfc-rebuild/`，可选双触发恢复快照为 `results/br-rebuild/`。旧 ECN、DCQCN 和 PFC 快照及候选模型已清理。

## 单交换机 PFC 与 DCQCN 协同

```bash
./scripts/run_pfc.sh all
python3 analysis/check_pfc.py
```

PFC 采用静态 DSCP 分类、四 RNIC 单 EtherSwitch、共享有限总缓冲和端口×priority 状态。RoCE 数据为 DSCP 24/priority 3，CNP 为 DSCP 0/priority 0；`PFC_MULTI_PRIORITY=1` 仅在隔离测试中把 QPN 2 数据设为 priority 0。P01—P10 覆盖格式、方向、多 QP、队头隔离、计时刷新、自动 Xoff/Xon、headroom、DCQCN 协同、生命周期和双栈回归。

主要环境参数为 `ENABLE_PFC=1`、`PFC_XOFF`、`PFC_XON`、`PFC_HEADROOM`、`PFC_PAUSE_QUANTA`、`PFC_DROP_XON_COUNT` 和 `RNIC_PFC_PORT_RESET_TIME`。交换机由真实入口占用生成 PFC；RNIC 接收侧自动 PFC 在下一节说明，RNR 不作为 PFC 条件。

PFC 帧为 60 B、无 Ethernet FCS，独立解析器为 `analysis/check_rocev2_pcap.py`。四组联合对照见 `results/pfc-four-modes.csv`，同轴事件见 `results/pfc-joint-timeseries.csv`，验收汇总见 `results/pfc-all.log`。

## RNIC 有限 RX、DMA 排空与自动 PFC

```bash
./scripts/run_rx.sh all
python3 analysis/check_rx.py
```

有限 RX 默认关闭；`ENABLE_RX_BUFFER=1` 开启共享总容量和 per-priority lease 计账，配合 `ENABLE_PFC=1` 后由 RNIC 真实接收占用自动生成 PFC。主要参数为 `RX_BUFFER_SIZE`、`RX_PFC_XOFF`、`RX_PFC_XON`、`RX_PFC_PAUSE_QUANTA`、`RX_PFC_REFRESH_INTERVAL`，压力通过既有 `DMA_DELAY`、`DMA_RETRY_COUNT` 注入。

大 payload 使用零拷贝，报文 context 中的共享 lease 随最后一个真实引用释放。RNR、QP Reset、故障注入和 RX 溢出保持不同语义。RX01—RX10 覆盖计账、溢出、自动暂停恢复、交换传播、headroom、操作类型、多 QP、Reset/晚到 DMA、RNR 和双栈回归。结果见 `results/rx-summary.csv`、`results/rx-joint-timeseries.csv`、`results/rx-validation.txt`，干净快照位于 `results/rx-rebuild/`。

## 双交换机逐跳 PFC 传播、恢复与 DCQCN 协同基线

```bash
./scripts/run_mspfc.sh all
python3 analysis/check_mspfc.py
```

固定拓扑为 A/B→SW1、C/D→SW2，SW1 与 SW2 由全双工 EtherLink 连接。两台交换机对四个 RNIC 使用显式 MAC→端口静态路由；PFC 只按本跳入端口发给相邻设备，不根据原始源 MAC 跨跳暂停，也不转发收到的 PFC。链路按方向记录 accepted/delivered 和在途字节，交换队列事件同时记录源/目的 MAC 与直接入端口。

MS01—MS10 分别覆盖静态基本转发、逐资源守恒、纯交换链路瓶颈、D 端 DMA 压力传播、独立刷新与恢复、仅 SW2 的 headroom 负例、共享路径优先级、双向与接收角色/Reset、CE 跨跳保持和 DCQCN 协同、双栈与既有回归。纯链路瓶颈使用 10 Mbps 交换机间链路且不加 DMA 延迟；端点压力对照使用每源 1 Gbps 固定 pacing，仅 D 增加 500 µs DMA 延迟；SW1/SW2 的 Xoff 分别为 138/256 B，RC 超时为 100 ms，避免将持续暂停误判为丢包或重试耗尽。DCQCN 参数及 RX lease 语义保持原基线。

结果见 `results/mspfc-all.log`、`results/mspfc-summary.csv` 和 `results/mspfc-joint-timeseries.csv`；时间序列包含 device/port/direction/priority、原始 MAC 和直接 ingress。干净恢复构建及实际运行记录见 `results/mspfc-validation.txt` 和 `results/mspfc-rebuild/`。结论仅覆盖这两台交换机和已列参数，不外推到任意多交换机拓扑。

## DCQCN 时间＋字节双触发恢复配置

```bash
./scripts/run_br.sh all
python3 analysis/check_br.py
```

冻结的时间触发配置仍为默认。通过 `DCQCN_DUAL_TRIGGER=1` 和 `DCQCN_BYTE_RECOVERY_BYTES` 显式选择可选配置；模型参数为 `--dcqcn-dual-trigger` 与 `--dcqcn-byte-recovery-bytes`。T/BC 分别按 Figure 7 推进并决定 FR/AI/HAI，字节事件不重置时间定时器，实际降速清零两种计数和字节余量。

字节计账位于真实 `sendPacket` 成功之后，范围与既有 isPaced 相同，按完整建模帧字节计算。PFC 暂停、排队、busy 和故障丢弃不计费，重传实际发送才计费。阈值等值触发，越过部分保留，同一报文可触发多个阈值。BR 代表流量使用 128 B 阈值并记录实际触发次数；默认 10 MB 参数不属于旧时间触发路径。

BR01—BR08 分别覆盖默认兼容、实际发送、阈值余量、双触发状态、阶段/重置、事件与 QP 生命周期、PFC/重传/pacing、双栈与交付。结果见 `results/br-all.log`、`results/br-summary.csv`、`results/br-timeseries.csv`、`results/br-validation.txt`；干净快照位于 `results/br-rebuild/`。MS 与 BR 结果分开登记。

## 当前结论边界

B01—B08 的已列限定场景、RC/QP/Atomic/MW 扩展、IPv6 代表场景、四端点 S01–S08、ECN/CNP E01–E10、DCQCN D01—D10、PFC P01—P10、RNIC RX01—RX10、双交换机 MS01—MS10 及可选双触发 BR01—BR08 已通过，详见 `docs/baseline_acceptance.md`。ECN 的 167 项不同 PASS 包含 E10 回归，不重复累加。当前仍未覆盖 Type 1 MW、全部 NAK/RC 状态、CPU/其他设备的全局原子性、IPv6 扩展头与分片、超过两台交换机的任意拓扑、标准 verbs 软件接入及独立实现互操作，不能称为完整 RoCEv2 环境。后续增强包括标准软件接入和独立互操作。

## Linux RXE 与标准 verbs 接入准备状态

RXE 环境核查已确认：内核为 5.4.0-216，rdma-core/libibverbs/provider 为 28.0，`rdma_rxe.ko` 与 `ib_uverbs.ko` 可用，iproute2 提供 `rdma` 命令，`ibv_rc_pingpong` 已安装。当前 `ib_uverbs` 已加载，但 `rdma_rxe` 未加载，且 `/dev/net/tap` 不存在；普通用户执行 `modprobe rdma_rxe` 和创建 TAP 均返回 `Operation not permitted`。因此 I01 的 RXE 设备自检与 I02 的实际帧互通尚未完成，需要管理员加载 `tun`、`rdma_rxe`，创建并配置隔离 TAP 后，再执行 `rdma link add ... type rxe netdev ...` 和 RXE 对 RXE 自检。

gem5 构建已启用 `USE_TUNTAP=1`。后续可选用 `EtherTap` 直接连接 TAP，或使用 `EtherTapStub` 的 TCP 连接及 32 位网络字节序帧长前缀；两种路径都需要保留原始 RoCEv2 帧并接通主机 TAP。桥接验收应记录报文对应的 gem5 tick、主机时间、轮询/缓冲状态和两端重试参数，桥接往返耗时不得解释为 RNIC 硬件延迟。

当前 `libhgrnic` 与 `HanGuDriver` 使用自定义 `/dev/hangu_rnic` ioctl/描述符 ABI，不是标准 libibverbs 接入。标准软件路径仍需实现模拟 uverbs 设备与内核 ABI、rdma-core provider、设备发现、PD/MR/CQ/QP 映射、doorbell 及异步事件通知，并用未修改的标准 verbs 程序验证真实请求进入 RNIC 和 Timing DMA 路径。
