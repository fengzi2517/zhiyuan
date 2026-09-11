# 固定检索基线实验

本报告由真实本地模型运行生成。语料为原创虚构资料，标注尚需人工复核；小样本结果不能代表真实业务质量。

- 数据：12 文档 / 24 块 / 60 问题。
- 语料 SHA256：58581d71b1a0e3c21390d45c3e0c6e5a351d8bc7c6c12bf21ccef704b60ee115
- 范围：精确余弦召回 + 生产筛选/重排；不包含 HNSW、意图识别、查询改写或答案生成。
- 无答案空检索率只检查是否返回资料，不能解释为模型拒答率或答案正确率。
- Recall、MRR、nDCG 只对有答案问题计算，空检索计零；相同块去重，相关性为二元标注。
- 查询耗时：single sequential pass per mode after warmup; query embedding + exact cosine + production selection/rerank; excludes startup/corpus encoding/LLM/DB/network; not a throughput benchmark

| 模式 / 划分 | 有答案 / 无答案 | Recall@4 | MRR@4 | nDCG@4 | 无答案空检索率 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense / dev | 24 / 6 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 88.8604 | 110.2208 |
| dense / test | 24 / 6 | 1.0000 | 0.9479 | 0.9609 | 0.0000 | 87.9120 | 103.2481 |
| dense_rerank / dev | 24 / 6 | 0.8750 | 0.8542 | 0.8596 | 0.8333 | 542.6393 | 687.5244 |
| dense_rerank / test | 24 / 6 | 0.9167 | 0.9167 | 0.9167 | 1.0000 | 637.6586 | 2392.9050 |

## 失败与排序不理想的样例

列出 Recall < 1、首位不是证据块、或无答案仍返回资料的问题；逐题分数、候选与 trace 见 results.json。

### dense

- atlas-negative（dev / unanswerable）：Atlas 的 OCR 使用哪款 GPU？ 证据块=[]，返回块=[1, 2]。
- boreal-negative（test / unanswerable）：Boreal 管理员的联系电话是什么？ 证据块=[]，返回块=[4, 3]。
- cedar-negative（dev / unanswerable）：Cedar 每月 API 采购预算是多少？ 证据块=[]，返回块=[5, 6]。
- delta-negative（test / unanswerable）：Delta 的备份机房在哪个城市？ 证据块=[]，返回块=[8, 7]。
- ember-negative（dev / unanswerable）：Ember 缓存服务器有多少 GB 内存？ 证据块=[]，返回块=[9, 10, 15, 5]。
- fjord-negative（test / unanswerable）：Fjord 的登录密码最少需要几位？ 证据块=[]，返回块=[11, 12, 23, 9]。
- garnet-negative（dev / unanswerable）：Garnet 使用哪个具体型号的交叉编码器？ 证据块=[]，返回块=[13, 14]。
- harbor-4（test / cross_language）：Which fields form the Harbor ingestion idempotency key? 证据块=[16]，返回块=[15, 16]。
- harbor-negative（test / unanswerable）：Harbor 工作进程使用什么操作系统？ 证据块=[]，返回块=[15, 16, 22, 3]。
- iris-negative（dev / unanswerable）：Iris 对不同语言分别使用哪种 tokenizer？ 证据块=[]，返回块=[17, 18, 13]。
- jade-3（test / paraphrase）：用户等很久才看到第一个字，应先拆哪些阶段？ 证据块=[20]，返回块=[9, 17, 21, 20]。
- jade-negative（test / unanswerable）：Jade 告警通知发送到哪个邮箱？ 证据块=[]，返回块=[19, 20, 6, 4]。
- kite-negative（dev / unanswerable）：Kite 团队上个月发布了多少次？ 证据块=[]，返回块=[21, 22, 5]。
- lotus-negative（test / unanswerable）：Lotus 的摘要模型每百万 token 多少钱？ 证据块=[]，返回块=[23, 24, 21, 3]。

### dense_rerank

- atlas-2（dev / identifier）：AT-413 表示什么？ 证据块=[1]，返回块=[]。
- atlas-3（dev / paraphrase）：文档处理没成功，原件过几天会清理？ 证据块=[2]，返回块=[]。
- garnet-4（dev / cross_language）：How many passages does Garnet keep for the generation context? 证据块=[13]，返回块=[]。
- garnet-negative（dev / unanswerable）：Garnet 使用哪个具体型号的交叉编码器？ 证据块=[]，返回块=[13]。
- harbor-4（test / cross_language）：Which fields form the Harbor ingestion idempotency key? 证据块=[16]，返回块=[]。
- jade-3（test / paraphrase）：用户等很久才看到第一个字，应先拆哪些阶段？ 证据块=[20]，返回块=[]。
- kite-4（dev / cross_language）：What must be restored together when rolling back Kite? 证据块=[22]，返回块=[21, 22]。

## 复现约束

results.json 包含源文件指纹、Git HEAD、模型快照/权重哈希、依赖、设备、参数和启动耗时。解释本结果时应引用语料与源码指纹；运行时尚未提交的文件不能只靠 Git HEAD 复现。

参数保持应用默认值，本轮没有根据保留集调参。后续优化仅用 dev 调参，test 用于固定方案验收；反复观察本 test 后，它不再是严格未知集，需要补充新的独立测试集。
