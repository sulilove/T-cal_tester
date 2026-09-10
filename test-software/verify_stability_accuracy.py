# -*- coding: utf-8 -*-
"""快速验证 stability / accuracy 计算逻辑（模拟一组数据）"""
import numpy as np

# ============ 模拟数据 ============
# 模拟 5 个通道（dev0~dev4），dev0/dev1 勾选 Stability，dev2/dev3/dev4 未勾选
# 时间范围 0 ~ 7500 秒（覆盖 T3 = 120 分钟 = 7200 秒）

rng = np.random.default_rng(42)
n = 7500
t = np.arange(n, dtype=float)  # 相对时间（秒）

data_buffer = {}
time_buffer = {}
for d in range(5):
    base = 100.0 + d * 2.0
    vals = base + rng.normal(0, 0.05, n)
    data_buffer[d] = list(vals)   # 用 list 模拟 deque
    time_buffer[d] = list(t)      # 用 list 模拟 deque

# auto_test_state 模拟：dev0(通道1)、dev1(通道2) 完成 T3
# T3 = 120 分钟（即 7200 秒），T0=30min, T1=60min, T2=90min
auto_test_state = {
    0: {'T0': 30.0, 'T1': 60.0, 'T2': 90.0, 'T3': 120.0,
        'std1': 0.04, 'std2': 0.05, 'avg1': 100.1, 'avg2': 100.2,
        'phase': 'complete', 'T0_time': None, 'T2_time': None},
    1: {'T0': 32.0, 'T1': 62.0, 'T2': 92.0, 'T3': 122.0,
        'std1': 0.05, 'std2': 0.06, 'avg1': 102.1, 'avg2': 102.2,
        'phase': 'complete', 'T0_time': None, 'T2_time': None},
}
# dev2/dev3/dev4 未勾选 Stability，不在 auto_test_state 中

devices = [
    {'enabled': True, 'auto_test': True},   # dev0 通道1 Stability
    {'enabled': True, 'auto_test': True},   # dev1 通道2 Stability
    {'enabled': True, 'auto_test': False},  # dev2 通道3 Main
    {'enabled': True, 'auto_test': False},  # dev3 通道4 Sec
    {'enabled': True, 'auto_test': False},  # dev4 通道5 User
]
_dev_row_count = 5

# ============ 验证 _build_accuracy_rows 核心逻辑 ============
def build_accuracy_rows(window_minutes=10):
    rows = []
    targets = [(4, 'User'), (0, 'Fix')]
    t3_min = None
    for d in (4, 0):
        st = auto_test_state.get(d)
        if st and st.get('phase') == 'complete' and st.get('T3') is not None:
            t3_min = float(st['T3'])
            break
    if t3_min is None:
        print("[accuracy] 未找到 T3")
        return rows
    win_sec = float(window_minutes) * 60.0
    t3_sec = t3_min * 60.0
    win_start_sec = max(0.0, t3_sec - win_sec)
    for dev_id, label in targets:
        entry = {'No.': label, 'Max': None, 'Avg': None, 'Min': None}
        tb = time_buffer.get(dev_id)
        db = data_buffer.get(dev_id)
        if tb is None or db is None or len(tb) == 0 or len(db) == 0:
            rows.append(entry)
            continue
        vals = []
        for i, v in enumerate(db):
            if i < len(tb):
                ts = float(tb[i])
                if win_start_sec <= ts <= t3_sec:
                    try:
                        vals.append(float(v))
                    except (TypeError, ValueError):
                        continue
        if vals:
            entry['Max'] = float(np.max(vals))
            entry['Avg'] = float(np.mean(vals))
            entry['Min'] = float(np.min(vals))
        rows.append(entry)
    return rows

# ============ 验证 summary 核心逻辑（含 fallback）============
def build_summary():
    def _safe(d, key):
        return auto_test_state.get(d, {}).get(key)
    def _val_or_calc(d, key):
        v = _safe(d, key)
        if v is not None:
            return v
        if not (0 <= d < _dev_row_count):
            return None
        if not devices[d].get('enabled', False):
            return None
        buf = list(data_buffer.get(d) or [])
        if buf:
            arr = np.asarray(buf[-600:], dtype=float)
            arr = arr[~np.isnan(arr)]
            if arr.size > 0:
                if key == 'avg2':
                    return float(np.mean(arr))
                if key == 'std2':
                    return float(np.std(arr))
        return None
    return {
        'Main': _val_or_calc(2, 'avg2'),
        'Sec': _val_or_calc(3, 'avg2'),
        'User': _val_or_calc(4, 'avg2'),
        'U-Std': _val_or_calc(4, 'std2'),
        'F-avg': _val_or_calc(0, 'avg2'),
        'M-avg': _val_or_calc(1, 'avg2'),
        'F-std': _val_or_calc(0, 'std2'),
        't0': _safe(0, 'T0'),
        't1': _safe(0, 'T1'),
    }

print("========== accuracy 验证 ==========")
acc = build_accuracy_rows()
for r in acc:
    print(r)

print("\n========== stability summary 验证 ==========")
s = build_summary()
for k, v in s.items():
    print(f"{k}: {v}")

print("\n========== 断言 ==========")
assert acc[0]['No.'] == 'User' and acc[0]['Avg'] is not None, "User 通道 accuracy 未计算"
assert acc[1]['No.'] == 'Fix' and acc[1]['Avg'] is not None, "Fix 通道 accuracy 未计算"
assert s['F-avg'] is not None, "F-avg 为空"
assert s['M-avg'] is not None, "M-avg 为空"
assert s['Main'] is not None, "Main(通道3) 未 fallback 计算"
assert s['Sec'] is not None, "Sec(通道4) 未 fallback 计算"
assert s['User'] is not None, "User(通道5) 未 fallback 计算"
assert s['U-Std'] is not None, "U-Std(通道5 std) 未 fallback 计算"
assert s['F-std'] is not None, "F-std(通道1 std) 为空"
print("全部通过！stability 与 accuracy 均能正确记录（含未勾选 Stability 通道的 fallback）。")
