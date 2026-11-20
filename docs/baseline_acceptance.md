# 当前基线验收记录

## 验收结论

当前已完成基础数据通路与保护基线，并进一步完成 RC 可靠性扩展：PSN 回绕、批量 outstanding、Sequence Error NAK、窗口回退重传、累积 ACK 和重试耗尽。B01—B08 仍只表示本文列出的限定测试范围；RC 扩展通过也不等于完整 RoCEv2 环境、全部 RC 状态机或商用 RNIC 互操作验收。

## 已验证能力

- RoCEv2 使用 Ethernet + IPv4 + UDP 4791 + 标准 12 字节 BTH；RC Write/Read、ACK 和 Read Response 使用标准 opcode。RoCEv2 不额外封装 GRH。
- RETH/AETH 使用网络字节序；报文包含并校验 ICRC。Read Response Middle 不携带 AETH，First/Last/Only 按对应格式生成。
- `analysis/check_rocev2_pcap.py` 独立解析实际 pcap，核对 IP/UDP 长度、IP 校验和、UDP 端口、BTH/RETH/AETH、ICRC、IP 方向、参考载荷和故障后的实际发送序列。
- QP 与 MR 都携带 PD；payload DMA 前检查完整 key、PD、有效状态、完整地址范围、本地/远端属性和读写权限。本地读保持 verbs 默认允许语义。
- gem5 DMA 读写完成由真实响应驱动；Write ACK 在目标 payload 写完成后发送，Read CQE 在本地 payload 写完成后生成。
- 支持双包 8192 B Write/Read 和三段 12288 B Read Response，最终各只有一次完整成功 CQE。
- PSN 按 24 位模序号更新和比较，已实际跨越 `0xfffffe → 0xffffff → 0 → 1`。
- 一次提交 8 个 Write 或 Read WR 均成功；不再以逐 WR 等待完成代替 outstanding 验证。
- 乱序请求触发 Sequence Error NAK，请求方按 NAK 的期望 PSN 回退并重发未确认窗口；多包 First 丢失时 First/Last 均重发。
- 累积 ACK 可在前序 ACK 连续丢失时完成整组 WR，避免不必要重传。重试耗尽映射为 `IBV_WC_RETRY_EXC_ERR`（12），后续未完成 WR 以 `IBV_WC_WR_FLUSH_ERR`（5）冲刷。
- 重传复用窗口原报文，不新增 WR；长 Read 的多个响应窗口项共享一个请求时，每次恢复只重发一次该请求。重复 Write 不再次执行目标 DMA，重复 Read Response 不再次产生本地写或 CQE。
- QP 生命周期子阶段已验证 12 项转换与属性检查：`RESET→INIT→RTR→RTS`、`RTS↔SQD`、`ERR→RESET→重新初始化`；非法转换、缺属性和无效 mask/MTU 被拒绝且原状态不变。
- 标准完成码已具名映射：本地保护错误为 `IBV_WC_LOC_PROT_ERR`（4），远端访问错误为 `IBV_WC_REM_ACCESS_ERR`（10），普通重试耗尽为 12，RNR 耗尽为 13，后续未完成 WR 冲刷为 5。RNR 等待、补充 RECV 后恢复及耗尽路径均已验收。

## B 类用例状态

| 用例 | 当前状态 | 实际证据与范围 |
|---|---|---|
| B01 合法 Write | 通过 | `fixed-write-completion` 固定 16 次全部成功；目标/本地摘要和 guard 正确；pcap 含 16 个 Write Only 与 16 个 ACK |
| B02 合法 Read | 通过 | `fixed-read-completion` 固定 16 次全部成功；目标不被改写、本地结果和 guard 正确；pcap 含 16 组 Read Request/Response Only |
| B03 key 与权限 | 通过已列场景 | 错误 rkey/lkey、失效 MR、远端/本地 PD 不匹配、远端读写未授权、Read 目的区不可写均拒绝；错误 CQE 为 0 字节且内存不变 |
| B04 MR 边界 | 通过已列场景 | 合法末尾、起点越界、末尾越界、地址加长度回绕均符合预期，见 `protect-legal-end`、`protect-mr-*` |
| B05 分段与映射 | 通过已列场景 | 覆盖 64+32 B DMA、偏移 4080 跨页写、双包 8192 B Read/Write 和三段 12288 B Read |
| B06 Timing 因果 | 通过已列实验 | 两端均为 timing；ACK/CQE 顺序检查通过；DMA 子事务响应和 retry 通过；默认/高延迟对照完成数为 1296/999 |
| B07 多上下文隔离 | 通过四场景矩阵 | 两组独立 QP/PD/MR 各自合法访问成功，交叉 PD 访问拒绝；第二 MR 与 guard 不变 |
| B08 RC 状态与重复 | 通过已列场景 | 原有七类故障及新增十一类回绕、outstanding、乱序、连续丢失、回退、三段响应和重试耗尽场景均通过 |

## RC 扩展结果目录

- `rc-state-psn-wrap-{write,read}`：真实 PSN 回绕。
- `rc-state-outstanding-{write,read}`：一次提交 8 个 WR，8 个成功完成。
- `rc-state-out-of-order-{write,read}`：后续请求先到时发送 Sequence NAK 并恢复。
- `rc-state-consecutive-ack-loss`：连续三个 ACK 丢失后由 PSN 3 累积确认。
- `rc-state-consecutive-request-loss`：连续两个请求丢失后回退恢复。
- `rc-state-multipacket-out-of-order`：双包首包丢失，回退重发 First/Last。
- `rc-state-multipacket-read-middle`：三段响应及 Middle 无 AETH。
- `rc-state-retry-exhausted`：两次恢复仍失败，返回耗尽和后续冲刷完成。

## RC Type 2B MW 验收

| 用例 | 状态 | 实际证据与范围 |
|---|---|---|
| MW01 绑定与访问 | 通过 | MW Read/Write/CAS/FAA 成功，远端失效后访问返回 10；IETH、接收 CQE 和 Atomic 旧值正确 |
| MW02 绑定拒绝 | 通过已列负例 | 缺少 MW_BIND、窗口越界、Remote Write 所需底层 Local Write 缺失均返回 `IBV_WC_MW_BIND_ERR`，无半生效授权 |
| MW03 本地失效与重绑定 | 通过 | 旧 key 拒绝、重复失效成功空操作、新 key 范围生效、释放后拒绝 |
| MW04 SEND_WITH_INV | 通过 | 零载荷与双包消息各消费一个 RECV；载荷、IETH、`IBV_WC_WITH_INV` 和 rkey 正确 |
| MW05 RNR 与重复包 | 通过 | RNR 等待后恢复，重复请求/ACK 丢失不重复写消息、消费 RQ 或产生成功接收 CQE |
| MW06 Timing 退休 | 通过 | 四笔 FAA 中失效时 `refs=3`；旧事务在 RETIRING 状态完成并释放后才发布失效完成，随后重绑定成功 |
| MW07 生命周期 | 通过已列场景 | QP ERR/RESET 不自动失效 MW；错误 QPN、绑定 MR 注销及 MW 释放后的访问均被拒绝 |
| MW08 复用与回绕 | 通过 | 两端各自复用同一 MW 对象，index 保持 `0x1`；tag 按 `fe → ff → 00 → 01` 回绕，当前 key Read 成功、旧 tag 拒绝，index=2 的重叠窗口不受影响 |

统一入口为 `./scripts/run_mw.sh all`，功能与 Timing 断言见 `analysis/check_mw.py`，最新回归汇总见 `results/ecn-e10-check.log`。Bind/Local Invalidate 不占用 RC PSN；SEND_WITH_INV 使用标准 opcode 和 4 字节 IETH。保守退休是本模型明确采用的实现策略，已发生的 Write/Atomic 更新不回滚。

## IPv6 RoCEv2 与双栈回归

- 端点支持通过 `ROCE_IP_VERSION=6` 选择 IPv6，默认 IPv4 行为保留；静态地址映射为 server `fd00::a`、client `fd00::b`。
- IPv6 使用 40 字节基本头和 UDP 4791。当前生成有效的非零 UDP 校验和，接收同时接受零值与有效非零值；这不表示 RoCEv2 必须使用非零校验和。ICRC 计算始终将 UDP checksum 字段替换为 `0xffff`，与线上取值无关。
- 17 个代表场景通过：固定 Read/Write、SEND、多包 SEND、两种 Immediate、RNR、CAS/FAA、Atomic 重放、多包 Read/Write、错误 key、重复请求、丢 Read Response、PSN 回绕及两类 MW 场景。
- `analysis/check_ipv6.py` 核对各场景状态与数据证据，`analysis/check_rocev2_pcap.py` 独立核对 IPv4/IPv6 布局、长度、地址、UDP、BTH 及 RETH/AETH/AtomicETH 等 RDMA 传输扩展头和 ICRC。最新结果见 `results/ecn-e10-check.log`。
- 本轮不包含 IPv6 扩展头、分片、动态邻居发现或 IPv4/IPv6 混合地址族会话。

## 四端点交换与有限队列基线

- 拓扑为四个独立 RNIC 端点与一台二层 EtherSwitch，MAC 预学习；IPv4、IPv6 分别运行，不使用宿主 bridge/TAP。
- 每个出口采用独立 FIFO 和按字节计量的有限缓冲，同一 tick 按接收端口编号仲裁；链路忙时保留报文重试，缓冲满才记录真实丢弃，不把忙状态当作 PFC。
- S01–S08 已覆盖基本 Read/Write/SEND、不同出口并行、双向 RC、三对一汇聚、512 B 缓冲溢出与恢复、低速链路排空、统计/时序守恒，以及多 QP、多包、跨页排空。
- 逐端口记录入队、发出、丢弃、当前占用、峰值和排队时延，满足 `enq = sent + drop + queued`，最终 outstanding 与队列均排空。端口发送字节含协议头、ACK 和重传，与应用去重有效载荷分开统计。
- `analysis/check_switch.py` 另核对完成数量、独立 pcap 地址族和故障恢复。统一入口为 `./scripts/run_switch.sh all`，最新结果见 `results/ecn-e10-check.log`。

## 双栈 ECN/CNP 反馈路径基线

- 交换机按“当前出口占用＋新报文长度”的预计字节数与阈值比较，达到或超过阈值时将 ECT(0)/ECT(1) 改为 CE；Not-ECT 不标记，已有 CE 保留。只有实际留在队列中的报文计入标记统计，缓冲溢出仍按原策略丢弃。
- IPv4 标记后更新头校验和；IPv6 只修改基本头 ECN 位并保持 DSCP 与 Flow Label。两种地址族均保持原 ICRC 有效，接收接受零值或有效非零 UDP 校验和。
- CNP 使用 UDP 4791、BTH opcode `0x81`、零 PSN/SE/M 和 16 字节全零 reserved，不附加 AETH。CNP 沿真实交换队列和链路返回被标记报文来源 QP；Read Response 的反馈返回响应发送端，而不是固定返回 Read 请求端。
- 每 QP 独立合并，首个 CE 立即生成 CNP，窗口内后续 CE 合并，跨窗口按 pending 状态补发；RESET 清理本地 pending 和通知状态。CNP 不推进普通 RC PSN、不消费 RQ、不占 Read/Atomic 额度，也不产生用户 CQE。
- ECN/CNP 阶段只验收标记、反馈和源 QP 通知；CNP 驱动的速率控制与 pacing 在下一节单独验收。

| 用例 | 状态 | 核心证据 |
|---|---|---|
| E01 功能关闭与低负载 | 通过 | 双栈均无 CE/CNP，既有 RC 完成不变 |
| E02 阈值与码点 | 通过 | 阈值等号、ECT(0)/ECT(1)、Not-ECT、已有 CE、DSCP/Flow Label 保持 |
| E03 报文完整性 | 通过 | 双栈 ICRC、UDP、IPv4 校验和、CNP 格式和篡改拒绝 |
| E04 完整反馈 | 通过 | 队列 CE→接收端 CNP→交换网络→源节点 QP；双栈各 50 个 CE、6 个 CNP 接收 |
| E05 三对一与多 QP | 通过 | 两个独立通信对各自 QPN 1/2 的反馈归属与合并状态独立，环形队列完成且排空 |
| E06 Read Response 方向 | 通过 | 双栈各 32 个 CE/CNP，CNP 只到两个响应发送端 |
| E07 合并与 RESET | 通过 | 首个 CE 立即反馈、复制请求在窗口内合并，接收端 RESET 后无迟到 CNP |
| E08 RC 资源隔离 | 通过 | Read 额度、RQ 消费、TX/RX 完成和 outstanding 均保持既有断言 |
| E09 CNP 丢失 | 通过 | 主动丢弃首个 CNP 后仍有后续反馈；双栈各 50 个 CE，生成 6、接收 5，普通 WR 全部成功 |
| E10 回归与排空 | 通过 | 统一入口 144 条 PASS；既有固定 Read/Write、保护、RC、QP、Atomic、MW、IPv6、S01–S08 回归与 18 个 ECN 运行队列排空 |

统一入口为 `./scripts/run_ecn.sh all`，独立检查为 `analysis/check_ecn.py` 和 `analysis/check_rocev2_pcap.py`。E01–E09 与 E10 分别见 `results/ecn-e01-e09-check.log`、`results/ecn-e10-check.log`；合计 167 项不同 PASS、0 条 FAIL。

## 双栈 DCQCN 控制与出口 pacing 基线

- 控制器固定参考 High-Precision-Congestion-Control 提交 `9f4be2a9ead8a90e8bf732c66bd758c00e58e5be` 的 Mellanox CX4+ 实现。α 周期更新、降速监测和恢复定时器分离；同一降速周期的多个 CNP 只产生一次降速。该默认配置仅使用时间驱动 FR/AI/HAI；原论文的时间＋字节双触发由后文可选 BR 配置单独验收。
- 逐包 pacing 已接入 `sauProcessing` 真实出口，按完整已建模帧字节计费并向上取整到 tick，不累积空闲突发。busy 不扣预算，实际发送和 RC 重传分别计费；pacer 中尚未发出的报文不启动等待 ACK 超时。
- SEND、Write、Read/Atomic 请求和 Read/Atomic 响应对应各自 QP 的速率；ACK/NAK/CNP 使用控制优先路径但仍占交换端口带宽。ERR/RESET 清除控制状态、旧事件和待发项，SQD/空闲 RTS 保留状态。
- 统一入口为 `./scripts/run_dcqcn.sh all`，最终检查摘要为 `results/dcqcn-all.log`，D01—D10 共 10 个验收组全部通过、0 个失败项。ECN 的 E10 144 项已包含在既有 167 项中，不与 DCQCN 组数或其他子集重复累加。

| 用例 | 状态 | 核心证据 |
|---|---|---|
| D01 禁用与固定速率 | 通过 | 138 B 报文在 10/20 Gbps 的实际间隔为 110400/55200 ps；禁用时不 pacing |
| D02 首个 CNP | 通过 | 首个降速 100→50 Gbps，持续流后续真实发包使用新速率 |
| D03 周期边界 | 通过 | 同 tick、同周期和跨周期反馈符合参考状态机，不在接收回调重复降速 |
| D04 恢复 | 通过 | α 衰减、FR/AI/HAI、速率上限及整数精度检查通过 |
| D05 计费与背压 | 通过 | 变长包、240 次注入 busy、预算和统计检查通过 |
| D06 响应与双向 | 通过 | CNP 后响应端 Read Response 实际降速，ACK/CNP 正常推进 |
| D07 多 QP | 通过 | QPN 1/2 状态独立、端口容量守恒、同 tick 选择函数重复一致 |
| D08 持续三对一 | 通过 | 反馈/DCQCN 对照各三流 100 WR 全部成功，同轴事件时间序列及去重 goodput 已导出 |
| D09 故障生命周期 | 通过 | CNP 丢失、真实链路丢包重传、ERR/RESET/重建通过 |
| D10 双栈回归 | 通过 | IPv6 DCQCN 代表场景、E01—E10 和既有全量回归通过，最终队列排空 |

D08 指标见 `results/dcqcn-d08-summary.csv`，同轴事件见两个 `results/dcqcn-d08-*/sustained/timeseries.csv`。控制器指定速率、实际发送速率和唯一 PSN goodput 分开报告，不要求所有性能指标都优于反馈基线。

## 单交换机 PFC 逐优先级流控与 DCQCN 协同基线

- 无 VLAN 报文按 `priority=DSCP>>3` 分类；RoCE 数据默认 DSCP 24/priority 3，CNP 为 DSCP 0/priority 0，ECN 两位独立。多优先级隔离测试可将 QPN 2 数据显式配置为 DSCP 0。
- PFC 使用真实 60 B MAC Control 帧：目的 MAC `01:80:c2:00:00:01`、EtherType `0x8808`、opcode `0x0101`、8 位 enable 和 8 个 16 位 quantum；不保存 Ethernet FCS。相邻端口本地消费，不进入泛洪或 RoCE QP。
- enable=0 不改变状态，非零 quantum 覆盖旧截止时间，零 quantum 释放；超时自然恢复。quantum 按接收端口物理线速的 512 bit 时间换算，不使用 DCQCN 速率。NIC 和交换机都保存端口×priority 状态，MAC Control 不受暂停，CNP 仍受 priority 0 调度。
- 交换出口保留单一物理总缓冲和同 priority 顺序，调度跳过被暂停类；每个报文记录 ingress/priority/计费字节。保护类按入口占用触发 Xoff/Xon，其他类准入容量为总缓冲减 headroom，PFC 帧仍经过真实出口串行化队列。
- PFC 不修改 QP 的 α/速率，恢复后继续经过既有 DCQCN pacing；QP Reset 不清除端口暂停状态。联合对照沿用已冻结的 HPCC/Mellanox 时间触发配置，不启用后文 BR 的可选字节触发。

统一入口为 `./scripts/run_pfc.sh all`，P01—P10 共 10 个验收组全部通过、0 个失败项，见 `results/pfc-all.log`。既有 E10 仍为 144 项 PASS，并包含在 ECN 的 167 项中。

| 用例 | 状态 | 核心证据 |
|---|---|---|
| P01 关闭与分类 | 通过 | 双栈 DSCP 映射一致，CE 不改变 priority，关闭时无 PFC 事件 |
| P02 格式与逐跳 | 通过 | 独立解析 RNIC/交换机实际 pcap，60 B、无 FCS、单跳消费不泛洪 |
| P03 方向与粒度 | 通过 | 同 priority 两个 QP 在暂停窗口内均停发，反方向不自动暂停 |
| P04 优先级调度 | 通过 | priority 3 队头暂停时 priority 0 仍发送，共享端口容量守恒 |
| P05 计时刷新 | 通过 | mask、长短刷新、零值释放、自然到期和线速 quantum 检查通过 |
| P06 Xoff/Xon | 通过 | 三个正确入口分别达到 512 B Xoff、降至 128 B Xon，PFC pcap 与迟滞通过 |
| P07 headroom | 通过 | 足额配置无溢出；2 kB 不足配置出现 11 次真实溢出和 11 次重传 |
| P08 DCQCN 协同 | 通过 | Write/Read Response、恢复后 pacing 和四种控制组合通过 |
| P09 控制与生命周期 | 通过 | Xon 丢失后自然到期、QP Reset 隔离、端口控制状态复位通过 |
| P10 双栈回归 | 通过 | IPv6 PFC、既有全量回归、独立 pcap 和最终排空通过 |

P07 足额场景使用 16 kB 总缓冲、512 B Xoff、128 B Xon 和 8 kB 预留；每流最多 8 个 138 B outstanding，实测每入口 Xoff 后额外占用不超过 592 B。结论只覆盖该负载、10 us 链路延迟及配置，不声称任意线速下的通用 headroom 保证。

四组结果见 `results/pfc-four-modes.csv`，联合时间序列见 `results/pfc-joint-timeseries.csv`，包含入口/出口占用、Xoff/Xon、PFC 区间、CE/CNP、控制速率、实际发包、headroom/溢出和重传。相同负载下不要求 DCQCN 必须减少所有 PFC 次数或提高所有指标。

## RNIC 有限接收缓存、DMA 排空与自动 PFC 闭环基线

- 每个接收报文按 `packet->length` 计入共享 RX 总容量和 per-priority 占用。`EthPacketData::context` 持有共享 RX lease，最后一个 `EthPacketPtr` 真实引用销毁时释放；不在 DMA、错误或 Reset 分支重复手工回收。
- Write、Read Response 和 SEND 大 payload 改为零拷贝，`MrReqRsp::requestPkt/sourcePkt` 与 `DmaReq::owner` 保持原报文存活。描述符和小 Atomic 暂存仍受既有 `reorder_cap` 上下文容量约束，没有新增无界 payload 暂存。
- 默认关闭有限 RX 功能；开启后容量不足产生独立 `RX_BUFFER_DROP`，与故障注入和 RNR 分开。保护类占用达到 Xoff 时 RNIC 自动排队发送 PFC，持续高于 Xon 时刷新，真实引用释放到 Xon 后发送零 quantum 恢复。
- RQ 缺 WQE 继续走 RNR；QP Reset 不直接清空端口 PFC 或其他 QP 的 RX lease，在途 DMA 晚到完成只释放自身引用。

统一入口为 `./scripts/run_rx.sh all`，RX01—RX10 共 10 个验收组全部通过、0 个失败项，见 `results/rx-all.log`。既有 E10 144 项 PASS 全部保持，并仍包含在 ECN 的 167 项中。

| 用例 | 状态 | 核心证据 |
|---|---|---|
| RX01 计账基线 | 通过 | 有限计账和零拷贝 Write/Read 正确，最终占用为 0，无误 PFC |
| RX02 有限溢出 | 通过 | 512 B RX 缓冲出现 37 次真实溢出，独立计数并由 RC 重传恢复 |
| RX03 自动暂停恢复 | 通过 | 100 µs DMA 压力下 7 次 Xoff/Xon、29 次刷新，排空后占用为 0 |
| RX04 背压传播 | 通过 | RNIC RX 压力使交换出口积累，再产生 6 次交换侧 Xoff 并通知上游 |
| RX05 RX headroom | 通过 | 4 kB 足额配置无溢出；1 kB 不足配置 51 次溢出并恢复 |
| RX06 接收操作 | 通过 | Write、Read Response、SEND/RECV、read credit 和多包生命周期通过 |
| RX07 多 QP | 通过 | 两 QP 共享容量、各自完成，最终所有 RNIC 占用为 0 |
| RX08 Reset/晚到 DMA | 通过 | ERR/RESET/重建成功，无陈旧重复释放或占用泄漏 |
| RX09 RNR 与刷新 | 通过 | 既有 RNR 恢复通过且未误触发 RX PFC，持续刷新独立验证 |
| RX10 双栈回归 | 通过 | IPv6 自动 PFC、既有回归、pcap 与最终排空通过 |

统一时间线见 `results/rx-joint-timeseries.csv`，对齐 RX 占用、DMA 完成/retry、lease 释放、Xoff/Xon、PFC 收发、交换队列和实际发包；汇总见 `results/rx-summary.csv`。结论限于单交换机、已列 DMA 延迟/retry 和有限缓冲配置，不外推为任意内存系统下的通用无丢包保证。

RX 回归使用 `model/csrna/build/X86/gem5.opt`，SHA-256 为 `e610beb0a3896a98f1df81ef3e4c674c109da1b2cccb41e1d4c5f966e43673c3`。干净副本验证使用 `results/rx-rebuild/csrna/build/X86/gem5.opt`，SHA-256 为 `9407947ea0fb1fbae2656ab0f47e23c988cb44c9eaadca15c2cd282a84a2c2cf`；30 个恢复文件一致、完整构建及 DMA 压力下自动 Xoff/Xon 实际运行通过。完整对应关系见 `results/rx-validation.txt`。

## 双交换机逐跳 PFC 传播、恢复与 DCQCN 协同基线

- 固定 A/B→SW1、C/D→SW2，SW1—SW2 为全双工 EtherLink。四个端点在两台交换机上均有显式静态 MAC→端口路由。SW2 将 A/B 的流量关联到共同的直接入链路，而不是原始源 MAC；PFC 在相邻端口本地消费，不跨跳转发。
- 每个交换出口继续满足 `enq = sent + drop + queued`；交换机间链路按方向分别满足 `accepted = delivered + in_flight`，最终队列、在途报文和 RX lease 均排空。交换事件保留原始源/目的 MAC 和直接 ingress，链路事件记录 accepted/delivered、bytes、priority 和在途占用。
- 交换链路瓶颈与 RNIC 压力分开：MS03 只降低 SW1—SW2 链路速率；MS04 使用每源 1 Gbps 固定 pacing 和 mode 57 三源负载，SW1/SW2 的 Xoff 分别为 138/256 B，仅 D 增加 500 µs DMA 延迟，并有正常内存对照。压力场景的 PFC quantum 为 10000，在 100 Gbps 为 51.2 µs；RC 超时为 100 ms，暂停延迟与实际丢包分别判定。
- DCQCN 继续使用冻结的 HPCC/Mellanox 时间触发配置，不启用后文 BR 的可选字节触发。CE 在首跳新标记后，后跳保留并计入 `ecn_already`；CNP 返回实际源 QP，恢复发送仍遵守既有 pacing。

| 用例 | 状态 | 核心证据 |
|---|---|---|
| MS01 基本转发 | 通过 | 本地、跨交换机及反向 RC，静态端口映射和双栈完成 |
| MS02 资源计账 | 通过 | 六端口守恒、双向链路在途守恒、RX 最终归零 |
| MS03 链路瓶颈 | 通过 | 正常内存下仅 SW1 的 A/B 入口产生 Xoff/Xon，无 RX 压力或溢出 |
| MS04 RNIC 压力链 | 通过 | D→SW2→SW1→A/B 与本地 C 分支，三组 mode 57 完成和正常对照 |
| MS05 刷新恢复 | 通过 | 各级独立 Xon、持续刷新停止、Xon 丢失自然到期、PFC 不转发 |
| MS06 局部 headroom | 通过已列配置 | 足额对照无溢出；仅 SW2 收紧后出现可定位丢弃及 RC 恢复 |
| MS07 优先级共享路径 | 通过 | A→D 暂停时同优先级 B→C 关联停顿，priority 0 继续进展 |
| MS08 双向与接收角色 | 通过 | 跨交换机双向 Write、Read Response、SEND、ERR/RESET/重建和晚到 DMA |
| MS09 ECN/DCQCN 协同 | 通过 | CE 跨跳保持、CNP 归属、速率恢复和真实出口 pacing |
| MS10 双栈与交付 | 通过 | IPv6、独立 pcap、最终排空、既有回归及干净恢复构建运行 |

统一入口为 `./scripts/run_mspfc.sh all`，独立检查为 `analysis/check_mspfc.py`。验收汇总见 `results/mspfc-all.log`，负载汇总和同轴事件分别见 `results/mspfc-summary.csv`、`results/mspfc-joint-timeseries.csv`，干净恢复对应关系见 `results/mspfc-validation.txt`。结论仅覆盖上述两交换机拓扑、负载和参数。

## DCQCN 时间＋字节双触发恢复配置

- 本阶段是独立可选配置，`--dcqcn-dual-trigger` 显式开启；默认仍为冻结的时间触发 HPCC/Mellanox 所选配置。BR 不修改 MS 的验收口径。
- 按 Figure 7 分别维护 T 与 BC：事件后推进对应计数，`max(T,BC)<F` 为 FR，`min(T,BC)>F` 为 HAI，其余为 AI。字节事件不重置时间定时器，实际降速清零 T、BC、字节余量和恢复阶段。
- 只对既有 isPaced 范围内的 RoCE 请求/响应在 `sendPacket` 成功后按完整已建模帧字节计账。排队、PFC 暂停、busy 和故障丢弃不计费；重传实际再次发送才再次计费。阈值等值触发，越过部分保留为余量，一个长报文可消费多个阈值。
- 代表流量使用 128 B 验收阈值，实际记录 `DCQCN_BYTE_ACCOUNT`、字节触发次数和 T/BC 状态；短场景未触发不会代替代表场景验收。

| 用例 | 状态 | 核心证据 |
|---|---|---|
| BR01 默认兼容 | 通过 | 默认无字节计账；逐 QP 报文/PSN/字节序列及首个降速、FR/AI/HAI 关键轨迹保持 |
| BR02 实际发送计账 | 通过 | 多包/跨页/环形流量，240 次 busy；成功 paced 发送与字节记录逐节点相等 |
| BR03 阈值与余量 | 通过 | 阈值前、等于、超过、多单阈值和跨包余量 |
| BR04 双触发状态 | 通过 | T/BC 独立推进，算法与实际流量均观察到时间和字节事件 |
| BR05 阶段与重置 | 通过 | Figure 7 边界、降速清零、最小/最大速率 |
| BR06 事件与生命周期 | 通过 | 同 tick 顺序、零字节重复、ERR/RESET/重建与旧事件隔离 |
| BR07 PFC/重传/pacing | 通过 | 暂停窗口不计账，实际重传计费，既有出口 pacing 保持 |
| BR08 对照与交付 | 通过 | 新旧配置、IPv6、E10 144 项及冻结 PFC/RX/MS 回归、干净恢复与校验 |

统一入口为 `./scripts/run_br.sh all`，独立检查为 `analysis/check_br.py`。汇总见 `results/br-all.log`、`results/br-summary.csv`、`results/br-timeseries.csv`，干净恢复见 `results/br-validation.txt` 和 `results/br-rebuild/`。结论仅覆盖所选双触发参数及已列场景，不声称与独立 RNIC 实现互操作。

## 可复跑命令

```bash
./scripts/build_model.sh
MAX_TICKS=150000000000 ./scripts/run_protection.sh all
MAX_TICKS=150000000000 ./scripts/run_fault.sh all
MAX_TICKS=150000000000 ./scripts/run_rc_state.sh all
python3 analysis/check_protection.py results/protect-* results/fault-* results/retry-cross-line-fixed
python3 analysis/check_fault.py results/fault-*
python3 analysis/check_rc_state.py results/rc-state-*
python3 analysis/check_fixed_rc.py results/fixed-write-completion results/fixed-read-completion
python3 analysis/check_completion_order.py
python3 analysis/check_retry.py
python3 analysis/check_rocev2_pcap.py results/protect-* results/fault-* results/fixed-*-completion
```

注意：若把构建日志命名为 `results/rc-state-*.log`，不要将其作为 `check_rc_state.py` 的目录通配输入。每次运行保存完整命令、源码差异、gem5 配置/统计、模拟日志以及双端 pcap。`tests/rocev2_format_test.cc` 另用于格式、篡改拒绝和 PSN 回绕比较检查。最新固定 Read/Write、保护、故障、RC、QP、DMA、Fence、Atomic、MW、IPv6 和交换场景的统一校验结果见 `results/ecn-e10-check.log`。

## 尚未覆盖

- 超出当前窗口的非法序号、全部 NAK 类型、完整多 QP 恢复调度和标准规定参数映射。
- Type 1 MW、其他 MW 类型/地址模式、CPU 或其他设备参与的全局原子性。
- IPv6 扩展头、分片、动态邻居发现和混合地址族会话；非默认 P_Key、超过两台交换机的任意拓扑、标准 verbs 软件接入及独立实现实际互操作。
- 对象版本、可信来源绑定和撤销协议；这些属于环境完成后的安全研究，不作为当前主线。
