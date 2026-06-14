import os
from pathlib import Path
from transformers import pipeline

# 默认从 HuggingFace 自动下载（约 400 MB，仅首次需要网络）
# 若已有本地模型，设置环境变量指向本地目录即可跳过下载，例如：
#   Windows: set SENTIMENT_MODEL_PATH=D:\local model\roberta-base-finetuned-jd-binary-chinese
#   Linux/Mac: export SENTIMENT_MODEL_PATH=/path/to/model
_HF_MODEL_ID = "uer/roberta-base-finetuned-jd-binary-chinese"

_classifier = None


def _resolve_model() -> str:
    local = os.environ.get("SENTIMENT_MODEL_PATH", "").strip()
    if local and Path(local).exists():
        return local
    return _HF_MODEL_ID


def _get_classifier():
    global _classifier
    if _classifier is None:
        try:
            import torch
            device = 0 if torch.cuda.is_available() else -1
        except ImportError:
            device = -1
        model_path = _resolve_model()
        _classifier = pipeline(
            "text-classification",
            model=model_path,
            tokenizer=model_path,
            device=device,
        )
    return _classifier


def _predict(text):
    """返回 0~1 的正面情感分数"""
    out = _get_classifier()(text[:512])[0]
    label = out['label'].lower()
    conf = out['score']
    # positive / label_1 → 正面概率 = conf
    # negative / label_0 → 正面概率 = 1 - conf
    if 'pos' in label or label == 'label_1':
        return conf
    else:
        return 1.0 - conf


def analyze_sentiment(comments):
    results = []
    for text in comments:
        try:
            score = _predict(text)
            label = '正面' if score >= 0.5 else '负面'
            results.append({'text': text, 'score': score, 'label': label})
        except Exception:
            continue
    return results


def print_report(results):
    if not results:
        print("没有可分析的评论")
        return

    positive = [r for r in results if r['label'] == '正面']
    negative = [r for r in results if r['label'] == '负面']
    avg_score = sum(r['score'] for r in results) / len(results)

    pos_pct = len(positive) / len(results)
    neg_pct = len(negative) / len(results)
    bar_len = 30

    print("\n====== 情感分析报告 ======")
    print(f"分析评论数  : {len(results)} 条")
    print(f"平均情感得分: {avg_score:.3f}  (0=极负面  1=极正面)")
    print()
    print(f"正面 {len(positive):4d}条 ({100 * pos_pct:5.1f}%)  {'█' * round(bar_len * pos_pct)}")
    print(f"负面 {len(negative):4d}条 ({100 * neg_pct:5.1f}%)  {'█' * round(bar_len * neg_pct)}")

    print("\n-- 最正面评论（前3条）--")
    for r in sorted(positive, key=lambda x: -x['score'])[:3]:
        print(f"  [{r['score']:.2f}] {r['text'][:60]}")

    print("\n-- 最负面评论（前3条）--")
    for r in sorted(negative, key=lambda x: x['score'])[:3]:
        print(f"  [{r['score']:.2f}] {r['text'][:60]}")


def analyze_single(text):
    score = _predict(text)
    label = '正面' if score >= 0.5 else '负面'
    bar = '█' * round(score * 20) + '░' * (20 - round(score * 20))
    print(f"\n情感得分: {score:.3f}  [{bar}]  {label}")


if __name__ == '__main__':
    from bilibili_spider import fetch_comments

    print("请选择模式：")
    print("  1. 输入一段话直接分析")
    print("  2. 抓取B站视频评论分析")
    mode = input("请输入模式（1/2）: ").strip()

    if mode == '1':
        text = input("请输入要分析的文字: ").strip()
        if text:
            analyze_single(text)
        else:
            print("输入不能为空")
    else:
        bvid = input("请输入B站视频BV号（如 BV1xx411c7mD）: ").strip()
        pages = input("抓取页数（每页20条，直接回车默认5页）: ").strip()
        max_pages = int(pages) if pages.isdigit() else 5

        comments = fetch_comments(bvid, max_pages)
        if not comments:
            print("未抓取到评论，请检查BV号是否正确")
        else:
            print(f"\n共抓取 {len(comments)} 条评论，开始情感分析...")
            results = analyze_sentiment(comments)
            print_report(results)
