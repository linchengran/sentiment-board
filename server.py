from __future__ import annotations

import threading
import time
import sys
import importlib
from pathlib import Path

# 确保优先从本文件所在目录加载 monitor_core
BASE_DIR = Path(__file__).resolve().parent
_base_str = str(BASE_DIR)
if _base_str in sys.path:
    sys.path.remove(_base_str)
sys.path.insert(0, _base_str)

# 清掉可能已经缓存的旧版 monitor_core，确保重新从磁盘加载
sys.modules.pop('monitor_core', None)

from flask import Flask, jsonify, request, send_file

from monitor_core import (
    create_task,
    delete_task,
    export_history_csv,
    get_source_types,
    load_tasks,
    run_due_tasks,
    run_task,
    save_tasks,
    seed_demo_data,
    build_dashboard,
    update_task,
    clear_data,
)

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

RUN_LOCK = threading.Lock()
SCHEDULER_STARTED = False


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/sources")
def api_sources():
    return jsonify({"sources": get_source_types()})


@app.get("/api/tasks")
def api_tasks():
    return jsonify({"tasks": load_tasks()})


@app.post("/api/tasks")
def api_create_task():
    try:
        task = create_task(request.get_json(force=True) or {})
        return jsonify({"task": task})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.patch("/api/tasks/<task_id>")
def api_update_task(task_id: str):
    try:
        task = update_task(task_id, request.get_json(force=True) or {})
        return jsonify({"task": task})
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.delete("/api/tasks/<task_id>")
def api_delete_task(task_id: str):
    try:
        delete_task(task_id)
        return jsonify({"ok": True})
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404


@app.post("/api/tasks/<task_id>/run")
def api_run_task(task_id: str):
    if not RUN_LOCK.acquire(blocking=False):
        return jsonify({"error": "已有采集任务正在运行，请稍后再试"}), 409
    try:
        result = run_task(task_id)
        return jsonify(result)
    except KeyError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400
    finally:
        RUN_LOCK.release()


@app.post("/api/run-due")
def api_run_due():
    if not RUN_LOCK.acquire(blocking=False):
        return jsonify({"error": "已有采集任务正在运行，请稍后再试"}), 409
    try:
        return jsonify({"results": run_due_tasks()})
    finally:
        RUN_LOCK.release()


@app.post("/api/demo")
def api_demo():
    try:
        return jsonify(seed_demo_data())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/clear")
def api_clear():
    try:
        task_id = (request.get_json(force=True) or {}).get("task_id", "")
        clear_data(task_id=task_id)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/dashboard")
def api_dashboard():
    task_id = request.args.get("task_id", "all")
    freq = request.args.get("freq", "30min")
    since = request.args.get("since", "")
    return jsonify(build_dashboard(task_id=task_id, freq=freq, since=since))


@app.get("/api/export")
def api_export():
    path = export_history_csv()
    return send_file(path, as_attachment=True, download_name="sentiment_events.csv")


def scheduler_loop():
    while True:
        time.sleep(15)
        if not RUN_LOCK.acquire(blocking=False):
            continue
        try:
            run_due_tasks()
        finally:
            RUN_LOCK.release()


def start_scheduler_once():
    global SCHEDULER_STARTED
    if SCHEDULER_STARTED:
        return
    SCHEDULER_STARTED = True
    thread = threading.Thread(target=scheduler_loop, daemon=True)
    thread.start()


if __name__ == "__main__":
    import os
    start_scheduler_once()
    port = int(os.environ.get("PORT", 5052))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
