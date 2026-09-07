# CrossScale 实验计划

## Claim 与推进顺序

CrossScale 不加速 GPU provisioning；它协调当前 ready capacity、未来容量 ETA 与租户请求控制。先验证 E0 → 单 GPU profiling → E1 → E2，再决定是否值得扩大到 E3–E7。所有图的趋势都是待检验假设，不预设 CrossScale 必须胜出。

本仓库实现了实验骨架、共享策略、真实流式压测与只读 Kubernetes 观察器。模拟器仅用于管线测试：固定 prefill/decode 服务率无法表达真实 continuous batching、KV 压力或 TPOT interference，不能用它确认论文结论。真实 EKS 部署、容量校准、正式重复实验尚需执行。

## 基线与公平性

- B0: 2 GPU fixed，透传 gateway。
- B1: 4 GPU 预先 Ready，同样 gateway；称 pre-provisioned reference，不声称是数学上界。
- B2: waiting queue → KEDA AverageValue target 5 → HPA → Karpenter。
- B3: 每租户最近 30 秒 P90 TTFT/TPOT 与 SLO 比值的最大值 → KEDA Value target 1。称 SLO-KEDA；没有实现或验证 llm-d 等价性。
- B4: 2 GPU fixed + tenant admission。
- B5: 同 B3 slow loop + desired-capacity admission，保留作为乐观容量消融。
- ready-only: 同 B3 slow loop + 只用 ready capacity 的 admission。比 B5 更关键的对照。
- B6: 同 slow loop + tenant admission + pending ETA deadline-aware deferral。
- no-tenant: B6 改为均等配额；当前仍使用租户 TTFT deadline，因此它是权重消融，不是完全删除租户 SLO。
- oracle-eta: 模拟中知道真实启动时间；真实实验只有 controlled-readiness 回放可以使用。

所有系统同一模型、tokenizer、GPU 类型、最大 replicas、scrape 窗口、HPA actuator、warmup、随机 trace seed。B3/B5/ready-only/B6 必须通过同一 gateway 采集 SLO。主实验关闭 scale-down；E7 必须另行打开并统一 scale-down policy。EKS HPA sync period 未必可调；记录实际配置，不将 KEDA pollingInterval=5s 说成 HPA 每 5 秒执行。

直接比较 B3 与 B6 时 admission 会改变 slow-loop 观测值；增加 **matched scale schedule** 实验（回放同一扩容时间点）来隔离 coordination 的因果收益。脚本不会自动把匹配控制实验当作已完成。

## Admission 原型与待验证假设

每租户 concurrency quota 为 ready slots 的权重分配；slots_per_replica 和 prefill_tokens_s 必须通过真实 profiling 配置，不把默认值当作 measured capacity。当前为保守静态配额，不支持闲置配额借用；报告利用率损失。B5 使用 desired slots 是故意设置的消融。

ETA 只允许等待，绝不发往未就绪 GPU。如果预测 ready time 加 margin 能落在剩余 TTFT budget 内，则短暂 defer；否则 reject。TTFT 从 load generator 的计划到达时间开始，包含 gateway queue 与客户端 dispatch lag。任何 admitted 请求始终发往 Kubernetes ready endpoint。

**可证伪点：**几十秒启动延迟远大于 A/B 的 0.5/1.5 秒 TTFT SLO，ETA 在 gap 大部分时间不能挽救这些请求，只可能改善临近 Ready 的决策。若 B6 与 ready-only 没有显著差异，应收缩 claim 或改进具有预测需求/服务模型的控制器，不能仅用 B5 证明 lag awareness。

观察器目前用 pending Pod creation + held-out E0 P90 做 ETA，不读取未来。它不是阶段条件化预测模型。超期 ETA 会保留预测误差；请求 deadline 限制等待。使用新 readiness 数据重新训练预测器属于后续扩展。

## Measurement contract

G_i = 同时满足 TTFT、TPOT 的 completed requests / 全部 offered requests。
WG = sum(w_i G_i) / sum(w_i)。缺少某租户样本时返回 null，不能悄悄改变权重。429、timeout、网络错误及 drain 结束未完成请求全部保留在分母。单 token 或缺失 usage 的响应不能测量 TPOT，记录为 error。

TPOT = (最后非空 text chunk 到达 - 首个非空 text chunk 到达)/(completion_tokens - 1)。不是把 SSE chunk 当作一个 token；但网络 coalescing 仍会影响时间观测。逐 token ITL tail 应同时从服务端 histogram 分析。P95/P99 延迟为 completed-only conditional metrics，必须与失败率并列，不单独以低延迟宣称成功。

每次运行保留 config、trace hash、每请求 JSONL、时间序列、summary。正式运行另外归档镜像 digest、vLLM/KEDA/Karpenter/Kubernetes 版本、模型 revision、tokenizer revision、HPA YAML、NodePool、EC2 instance IDs、缓存条件和 Prometheus 原始查询输出。成本必须使用 EC2 启动至终止的计费生命周期；ready_gpu_hours 只是诊断量。

全程 open-loop Poisson arrival，同 seed 重放同 trace；不因响应慢而降低 offered RPS。报告客户端 dispatch lag，负载机落后时判为无效运行。长度为截断 lognormal，默认上限各 16K；校验实际模型总 context 上限。使用模型 tokenizer 生成真实文本 token corpus，避免以字符数冒充 token 数。

## E0：扩容耗时与 ETA 数据

每种条件至少 30 次独立 scale-out，包含成功与失败。2 → 4 GPU，observer 必须在扩容前启动。仅在专用实验 namespace/nodepool 中进行缩扩容；每轮恢复 initial capacity 并确认前轮节点清理结束。

分别命名 cached-on-existing-node、prebaked-image-new-node、cold-new-node。新节点不会自动继承旧节点本地缓存，不能笼统说 warm cache。记录 Pod creation、PodScheduled、container running.startedAt、Ready condition；用 Pod nodeName 关联 Node，再用 providerID 关联 NodeClaim。并行阶段不能简单串行相加。

observer 记录完整对象，e0-summary 提取 scale-up 至全部目标 ready 的轮询时间差，缺失/中断标记 censored。起点是观察到 spec.replicas 改变，不是精确 HPA decision；误差约为轮询间隔加多次 API 请求耗时。报告每个新增 Pod 的 readiness 时间，以及整次新增容量全部 ready 的时间。20–30 样本的经验 P99 极不稳定：保留原始样本、置信区间，不把 P99 当高精度结论。

前 2/3 independent episodes 用作 ETA calibration，后 1/3 held out。只有训练集可用于 P90 ETA；E5 不得读取该次真实 ready time，除单独 oracle。

## Profiling：负载校准

先固定一副本、禁用 autoscaling/admission、完成模型 warmup。对固定 tenant mix 扫描至少 6 个 RPS 点，每点 >= 180 秒，3 个 seed；用所有租户满足预先选择的 G_i 阈值（如 0.95）定义 sustainable RPS，不用 raw tokens/s 代替。额外验证 2 副本 scaling efficiency，不能默认完全线性。

calibrate 命令接受 measured single-replica RPS，生成 0.65/1.65/0.65 × initial capacity 的三阶段负载。具体 thresholds 与样本数必须实验前固定。默认配置只用于 smoke test。

## E1：Provisioning gap 是否伤害 SLO

B2 和 B3，2→4 GPU，0–60 秒 normal、60–180 秒 burst、180–300 秒 recovery。叠加 offered RPS、desired、ready、逐租户 P99 TTFT；按样本到达 cohort 分 5 秒窗口，小样本窗口标记缺失。阴影从 observed scale decision 到新增容量全部 ready，并标记每个 replica readiness。保持同样请求的 timeout/rejection 计数。至少 5 paired seeds；scale-out lag 自然变化是解释变量。

## E2：主要比较与 go/no-go

B0–B6 + ready-only，随机化执行顺序，每个 baseline >=5 independent repetitions，相同 seed 配对。报告整体及 burst cohort WG、每租户 G_i、rejections、timeouts、completed tokens/s、TTFT/TPOT tails。配对 run-level bootstrap 95% CI，不能把相关请求当独立重复。预先写出最小实用收益（建议 WG +0.05，仅为拟定标准）。

继续 E3–E7 的条件：B6 相对 tuned B3 和 ready-only 的收益超过预设阈值且置信区间支持；C 的最低 G_i 和 rejection cap 达到预设限制。若失败，保留负结果并检查 admission、预测质量、SLO 可行性，不挑种子。

## E3–E7 后续实验

- E3: A/B 固定，C 到达率乘 5；报告 A/B/C goodput、C rejection/defer/eventual completion、防饥饿最低服务份额。当前控制器只有配额，不保证最低 G_i。
- E4: ready gating 注入 0/15/30/60/90/120 秒 **总延迟**，在预先启动但不向 Service 暴露的 replicas 上做。普通 cold startup 上再 sleep 测到的是附加延迟，不能称 total lag。当前矩阵实现 simulation sweep；真实 readiness gate 未实现。
- E5: ETA relative error -100/-50/-25/0/+25/+50/+100%，单独 oracle ETA，记录真实误差、bias 与 stale predictions。矩阵提供模拟 sweep；真实注入需修改 observer 输出 ETA 或专用 replay。
- E6: B2、ready-only、no-tenant、B6、oracle；当前 no-tenant 仅权重消融，完全移除 tenant SLO 的版本需独立定义。
- E7: 30–60 分钟 trace，统一 scale-down 后扫描 cost knobs，取得多点 cost–SLO frontier；目前 long-trace smoke matrix 禁止据此宣称 cost savings，它没有真实 billing 或 scale-down。

## 官方接口参考

- [KEDA Prometheus scaler](https://keda.sh/docs/2.20/scalers/prometheus/)：单值 query 与 threshold；使用已安装版本对应文档验证配置。
- [HPA algorithm](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)：Value 与 AverageValue 语义不同；保留实际生成的 HPA 检查。
- [vLLM production metrics](https://docs.vllm.ai/en/latest/usage/metrics/)：指标随版本变化。该框架客户端测量 tenant SLO，不假定 vLLM 原生指标含 tenant label。
