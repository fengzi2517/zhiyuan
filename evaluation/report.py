"""Write inspectable metrics and per-question failures, without invented interpretation."""

import json
from pathlib import Path


def _number(value):
    return "—" if value is None else f"{value:.4f}"


def write_report(report, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    k = report["parameters"]["k"]
    lines = [
        "# 固定检索基线实验",
        "",
        "本报告由真实本地模型运行生成。语料为原创虚构资料，标注尚需人工复核；小样本结果不能代表真实业务质量。",
        "",
        f"- 数据：{report['dataset']['documents']} 文档 / {report['dataset']['chunks']} 块 / {report['dataset']['queries']} 问题。",
        f"- 语料 SHA256：{report['dataset']['sha256']}",
        "- 范围：精确余弦召回 + 生产筛选/重排；不包含 HNSW、意图识别、查询改写或答案生成。",
        "- 无答案空检索率只检查是否返回资料，不能解释为模型拒答率或答案正确率。",
        "- Recall、MRR、nDCG 只对有答案问题计算，空检索计零；相同块去重，相关性为二元标注。",
        f"- 查询耗时：{report['timing_scope']}",
        "",
        f"| 模式 / 划分 | 有答案 / 无答案 | Recall@{k} | MRR@{k} | nDCG@{k} | 无答案空检索率 | p50 ms | p95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, run in report["runs"].items():
        for split, summary in run["by_split"].items():
            values = " | ".join(_number(summary[key]) for key in
                                ("recall", "mrr", "ndcg", "unanswerable_empty_rate",
                                 "latency_p50_ms", "latency_p95_ms"))
            lines.append(f"| {mode} / {split} | {summary['answerable_count']} / "
                         f"{summary['unanswerable_count']} | {values} |")
    lines += ["", "## 失败与排序不理想的样例", "",
              "列出 Recall < 1、首位不是证据块、或无答案仍返回资料的问题；逐题分数、候选与 trace 见 results.json。", ""]
    for mode, run in report["runs"].items():
        lines += [f"### {mode}", ""]
        count = 0
        for row in run["results"]:
            metric = row["metrics"]
            failed = (metric["recall"] is not None and
                      (metric["recall"] < 1 or metric["mrr"] < 1))
            failed = failed or (not row["gold_ids"] and bool(row["retrieved_ids"]))
            if failed:
                count += 1
                lines.append(f"- {row['id']}（{row['split']} / {row['category']}）：{row['query']} "
                             f"证据块={row['gold_ids']}，返回块={row['retrieved_ids']}。")
        if not count:
            lines.append("- 本次固定样本没有上述失败；仍不能推断对未知业务问题同样有效。")
        lines.append("")
    lines += ["## 复现约束", "",
              "results.json 包含源文件指纹、Git HEAD、模型快照/权重哈希、依赖、设备、参数和启动耗时。"
              "解释本结果时应引用语料与源码指纹；运行时尚未提交的文件不能只靠 Git HEAD 复现。",
              "",
              "参数保持应用默认值，本轮没有根据保留集调参。后续优化仅用 dev 调参，test 用于固定方案验收；"
              "反复观察本 test 后，它不再是严格未知集，需要补充新的独立测试集。", ""]
    (destination / "summary.md").write_text("\n".join(lines), encoding="utf-8")
