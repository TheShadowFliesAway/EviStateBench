# Action Scripts

这里保存 recorder 可以 replay 的 primitive JSONL 动作脚本。

这些文件是 action source，不是 observation 或 hidden truth。`run_pilots.py`
从 manifest 读取 `primitive_jsonl` 后把它传给 `live_recorder.py`。
