# 舆情监控看板

一个面向个人使用的多来源舆情监控网页应用。用户可以创建监控任务，定时采集视频评论、热门话题、RSS 订阅或自定义文本，系统会自动进行情感分析、趋势聚合、负面占比统计、关键词提取和舆情拐点检测。

## 项目亮点

- 多来源采集：支持 B站视频评论、B站关键词视频评论、B站热门视频、微博热搜、知乎热榜、RSS 和自定义文本。
- 自动化监控：任务支持启用/暂停、手动执行、按间隔自动执行。
- 情感趋势分析：按时间粒度聚合平均情感分和负面占比，识别口碑变化。
- 舆情拐点检测：基于情感分变化和负面占比变化标记异常波动。
- 可视化看板：Flask 提供 API，原生 HTML/CSS/JS 绘制趋势图、任务列表、关键词和明细表。
- 可演示数据：内置一键演示数据，避免作品展示时依赖第三方平台接口稳定性。

## 技术栈

- 后端：Flask、Requests、Pandas
- 前端：HTML、CSS、原生 JavaScript、SVG
- 数据：CSV 持久化历史文本，JSON 持久化监控任务
- NLP：优先复用项目根目录 `analyze_bilibili.py` 的情感模型；模型不可用时降级为词典规则打分

## 目录结构

```text
舆情监控看板/
├── server.py              # Flask API 与任务调度入口
├── monitor_core.py        # 采集、情感分析、持久化、趋势与拐点逻辑
├── static/
│   ├── index.html         # 页面结构
│   ├── styles.css         # 看板样式
│   └── app.js             # 前端状态、API 调用和 SVG 图表
├── requirements.txt
└── README.md
```

## 运行方式

在项目根目录运行：

```powershell
cd C:\Users\linchengran\OneDrive\Desktop\day2\imdb_sentiment
python .\舆情监控看板\server.py
```

浏览器打开：

```text
http://127.0.0.1:5052
```

如果缺少依赖：

```powershell
pip install -r .\舆情监控看板\requirements.txt
```

## 使用建议

1. 先点击页面右上角“载入演示数据”，确认趋势图、拐点和明细效果。
2. 新建 B站视频或关键词任务，点击任务卡片里的“执行”。
3. 如果要长期监控，将任务保持“运行中”，后端会按设置的间隔自动采集。

## 数据文件

本地运行时会生成：

```text
舆情监控看板\data\tasks.json
舆情监控看板\data\sentiment_events.csv
```

`data/` 已加入 `.gitignore`，适合把代码上传到 GitHub 时保留隐私和轻量仓库。

## 简历描述示例

多来源舆情监控看板：基于 Flask + 原生前端实现个人可用的舆情分析系统，支持 B站评论、热门话题、RSS 和自定义文本采集；设计任务调度、CSV/JSON 本地持久化、情感趋势聚合、负面占比统计、关键词提取和拐点检测，并通过 SVG 实现无第三方图表库的交互式网页看板。
