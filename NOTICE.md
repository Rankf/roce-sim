# 来源、版权与许可说明

## 本仓库内容

本仓库包含独立构建/运行脚本、分析检查器、测试、文档、验收摘要和针对上游模型的修改补丁。仓库不包含上游完整源码、构建产物或任何访问凭证。首次设置时，`scripts/setup_model.sh` 从下列固定上游提交获取源码并应用补丁。

## csRNA / Han Gu RNIC Simulator

- 项目：https://github.com/ncsg-group/csRNA
- 固定提交：`5270d51c584055fb21f05602d624c2bcfb4184c7`
- 原始 RNIC 文件包含 Kang Ning、NCIC、ICT、CAS 的版权及“原样”声明。
- 许可文件：
  - https://github.com/ncsg-group/csRNA/blob/5270d51c584055fb21f05602d624c2bcfb4184c7/LICENSE
  - https://github.com/ncsg-group/csRNA/blob/5270d51c584055fb21f05602d624c2bcfb4184c7/COPYING

上游许可采用 BSD 风格条款，允许修改和再分发，但要求保留版权、许可条件和免责声明。该许可并非禁止商用许可。`COPYING` 同时说明主体采用 BSD/MIT 类许可，个别文件可能有其自身声明，应以各文件为准。

## gem5

- 项目：https://www.gem5.org/
- 本环境报告的基础版本：20.1.0.2。
- gem5 及其附带组件的版权和许可随上游分发提供。使用、修改和再分发时应同时保留相应声明。

## DCQCN 算法参考

- High-Precision-Congestion-Control：
  https://github.com/alibaba-edu/High-Precision-Congestion-Control
- 参考提交：`9f4be2a9ead8a90e8bf732c66bd758c00e58e5be`
- 用途：冻结的 Mellanox CX4+ 时间触发控制器和真实出口 pacing 的算法参考。

DCQCN 论文：

- Yibo Zhu 等，*Congestion Control for Large-Scale RDMA Deployments*，SIGCOMM 2015。
- https://conferences.sigcomm.org/sigcomm/2015/pdf/papers/p523.pdf
- 可选 BR 配置参考 Figure 7 的时间与字节双触发恢复机制。

上述论文和参考实现仅用于算法说明与实现核对，不代表其作者或机构认可本仓库。

## 修改、再分发与免责声明

上游代码及其修改部分继续适用上游原始版权和许可条款，不因本仓库的说明而改变。引用、修改或再分发时，应保留上游版权、许可和免责声明；不得将“ All Rights Reserved ”或本说明错误解释为禁止商用，也不得把本仓库的说明视为替代上游许可证。

本仓库按“原样”提供。验收记录只覆盖文档明确列出的模型、参数和场景，不构成生产环境安全性、商用 RNIC 互操作性、独立实现一致性或适用于特定用途的保证。
