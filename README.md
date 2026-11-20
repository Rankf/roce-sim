# RoCEv2 csRNA / gem5 仿真环境

本仓库提供可重建的 RoCEv2 csRNA/gem5 交付，包括 RC、双栈、ECN/CNP、DCQCN、PFC、有限 RX、双交换机逐跳流控，以及可选的 DCQCN 时间＋字节双触发恢复配置。

## 交付方式

- 上游模型：[ncsg-group/csRNA](https://github.com/ncsg-group/csRNA)，固定提交 `5270d51c584055fb21f05602d624c2bcfb4184c7`。
- 当前改动以 `patches/csrna-rocev2-protection.patch` 提供，设置脚本在克隆位置应用，不覆盖已有修改。
- `analysis/`、`scripts/`、`tests/`、`docs/` 和文本验收摘要随仓库提供。
- 不上传 gem5 构建树、模拟二进制、pcap、完整仿真日志、本地 Python 包或任何凭证。它们在本地生成，并由 `.gitignore` 排除。

## 环境要求

推荐 Ubuntu 20.04 x86_64、GCC/G++ 9.4、Python 3.8、`python3-config`、GNU Make、git 和 pip。无需 Docker。首次设置需要访问 GitHub 和 PyPI；之后构建不依赖绝对路径。

## 获取、设置与构建

```bash
git clone https://github.com/Rankf/roce-sim.git
cd roce-sim
./scripts/setup.sh
JOBS=16 ./scripts/build_model.sh
```

`setup.sh` 会：

1. 将上游 csRNA 克隆到 `model/csrna/` 并检出固定提交。
2. 应用当前完整补丁和构建兼容补丁。
3. 在 `env/python38-packages/` 安装固定版本 SCons 3.1.2 与 six 1.16.0。

已有模型目录若提交或补丁不匹配，会报错并保持原样，不会强制重置。可用 `CSRNA_UPSTREAM_URL` 覆盖上游镜像地址。

## 快速运行

```bash
./scripts/run_smoke.sh
RUN_ID=my-write ./scripts/run_rc.sh write
RUN_ID=my-read ./scripts/run_rc.sh read
```

生成的文件位于 `results/<run_id>/`，包括命令、参数、模拟日志、gem5 配置/统计和 pcap。

## 阶段验收

```bash
./scripts/run_dcqcn.sh all
./scripts/run_pfc.sh all
./scripts/run_rx.sh all
./scripts/run_mspfc.sh all
./scripts/run_br.sh all
```

不重跑仿真时，可使用随仓库提供的文本摘要核对交付记录：

```bash
wc -l results/dcqcn-all.log results/pfc-all.log results/rx-all.log \
  results/mspfc-all.log results/br-all.log results/ecn-e10-check.log
```

预期分别为 14、10、10、10、8、144 行。`results/br-validation.txt` 和 `results/mspfc-validation.txt` 记录干净恢复、二进制摘要和验收范围。完整检查结果、CSV、pcap 和恢复构建由相应脚本重新生成；未上传的大文件不影响源码恢复和运行。

## 当前范围

- 默认 DCQCN 仍为冻结的 HPCC/Mellanox 时间触发配置。
- `DCQCN_DUAL_TRIGGER=1` 显式选择可选时间＋字节双触发；验收阈值为 128 B，旧默认路径不启用字节触发。
- MS01—MS10 覆盖指定的双交换机拓扑；BR01—BR08 独立验收，不与 MS 混算。
- 不声称完整覆盖所有 RC/NAK 类型、任意多交换机拓扑、标准 verbs 接入或独立 RNIC 实现互操作。

详细构建参数和阶段说明见 `docs/environment_setup.md` 与 `docs/baseline_acceptance.md`。
