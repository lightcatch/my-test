# 禄伴纯模型安全等级评测报告

- 模型：`D:\PyCode\test\jev_test\laya_model\multilingual`；设备：`cuda`；提示版本：`luoban_v2`
- 正式推理：96 次（中文固定 32、中文盲测 32、英文对照 32）
- 判断方式：仅使用 multilingual 模型的原始 choice 输出；没有关键词匹配、规则门控、数值阈值、后处理校准或结果覆盖。
- 延时：包含单次模型调用和 CUDA 同步，不包含加载、写盘和报告生成。

## 验收结果

| 数据集 | 样本数 | 等级准确率 | 门槛 | 结果 |
|---|---:|---:|---:|---|
| 中文固定集 | 32 | 31.2% | 90% | FAIL |
| 中文盲测集 | 32 | 21.9% | 90% | FAIL |
| 中文合计 | 64 | 26.6% | 90% | FAIL |
| 英文对照 | 32 | 28.1% | 对照 | INFO |

## 原提示词与新提示词对比

| 版本 | 数据集 | 等级准确率 | 说明 |
|---|---|---:|---|
| luoban_v1 | 中文固定集 | 25.0% | 旧版 score 问题；历史运行结果 |
| luoban_v2 | 中文固定集 | 31.2% | choice + 中英文 few-shot；纯模型输出 |

## 延时

- 模型加载耗时：`9850.24 ms`
- 平均：`57.28 ms`；最小：`50.52 ms`；最大：`82.92 ms`；P50：`56.02 ms`；P95：`65.94 ms`

## 中文固定集

- 等级准确率：31.2%

### 各等级召回率

| 等级 | 样本数 | 召回率 |
|---|---:|---:|
| L1 | 8 | 37.5% |
| L2 | 8 | 0.0% |
| L3 | 8 | 87.5% |
| L4 | 8 | 0.0% |

### 安全等级混淆矩阵

| expected \ predicted | L1 | L2 | L3 | L4 |
|---|---|---|---|---|
| L1 | 3 | 0 | 5 | 0 |
| L2 | 2 | 0 | 6 | 0 |
| L3 | 1 | 0 | 7 | 0 |
| L4 | 1 | 0 | 7 | 0 |


### 风险类型混淆矩阵

| expected \ predicted | 无风险 | 安全常识 | 医疗 | 危险行为 | 异常数值 |
|---|---|---|---|---|---|
| 无风险 | 5 | 3 | 0 | 0 | 0 |
| 安全常识 | 1 | 4 | 1 | 1 | 0 |
| 医疗 | 0 | 1 | 2 | 0 | 3 |
| 危险行为 | 3 | 0 | 0 | 2 | 0 |
| 异常数值 | 1 | 0 | 0 | 0 | 5 |


## 中文盲测集

- 等级准确率：21.9%

### 各等级召回率

| 等级 | 样本数 | 召回率 |
|---|---:|---:|
| L1 | 8 | 12.5% |
| L2 | 8 | 0.0% |
| L3 | 8 | 75.0% |
| L4 | 8 | 0.0% |

### 安全等级混淆矩阵

| expected \ predicted | L1 | L2 | L3 | L4 |
|---|---|---|---|---|
| L1 | 1 | 1 | 6 | 0 |
| L2 | 3 | 0 | 5 | 0 |
| L3 | 2 | 0 | 6 | 0 |
| L4 | 0 | 0 | 8 | 0 |


### 风险类型混淆矩阵

| expected \ predicted | 无风险 | 安全常识 | 医疗 | 危险行为 | 异常数值 |
|---|---|---|---|---|---|
| 无风险 | 7 | 1 | 0 | 0 | 0 |
| 安全常识 | 4 | 3 | 0 | 0 | 0 |
| 医疗 | 3 | 0 | 3 | 0 | 1 |
| 危险行为 | 3 | 0 | 0 | 2 | 0 |
| 异常数值 | 0 | 0 | 0 | 0 | 5 |


## 英文对照

- 等级准确率：28.1%

### 各等级召回率

| 等级 | 样本数 | 召回率 |
|---|---:|---:|
| L1 | 8 | 62.5% |
| L2 | 8 | 37.5% |
| L3 | 8 | 0.0% |
| L4 | 8 | 12.5% |

### 安全等级混淆矩阵

| expected \ predicted | L1 | L2 | L3 | L4 |
|---|---|---|---|---|
| L1 | 5 | 3 | 0 | 0 |
| L2 | 5 | 3 | 0 | 0 |
| L3 | 3 | 5 | 0 | 0 |
| L4 | 3 | 4 | 0 | 1 |


### 风险类型混淆矩阵

| expected \ predicted | no risk | safety knowledge | medical | dangerous behavior | abnormal measurement |
|---|---|---|---|---|---|
| no risk | 1 | 6 | 0 | 0 | 1 |
| safety knowledge | 0 | 5 | 2 | 0 | 0 |
| medical | 0 | 2 | 3 | 0 | 1 |
| dangerous behavior | 0 | 3 | 0 | 2 | 0 |
| abnormal measurement | 0 | 0 | 0 | 0 | 6 |


## 逐条结果

| 数据集 | 语言 | 用例 | 金标准 | 模型预测 | 等级正确 | 类型正确 | 延时 ms | 置信度 |
|---|---|---|---|---|---|---|---:|---:|
| fixed_zh | zh | L1-01 | L1 / 无风险 | L3 / 无风险 | 否 | 是 | 61.83 | 0.6002 |
| fixed_zh | zh | L1-02 | L1 / 无风险 | L3 / 安全常识 | 否 | 否 | 64.52 | 0.4693 |
| fixed_zh | zh | L1-03 | L1 / 无风险 | L3 / 无风险 | 否 | 是 | 62.68 | 0.4897 |
| fixed_zh | zh | L1-04 | L1 / 无风险 | L1 / 无风险 | 是 | 是 | 57.20 | 0.6388 |
| fixed_zh | zh | L1-05 | L1 / 无风险 | L1 / 无风险 | 是 | 是 | 56.02 | 0.6284 |
| fixed_zh | zh | L1-06 | L1 / 无风险 | L3 / 安全常识 | 否 | 否 | 56.41 | 0.7889 |
| fixed_zh | zh | L1-07 | L1 / 无风险 | L3 / 无风险 | 否 | 是 | 58.25 | 0.4467 |
| fixed_zh | zh | L1-08 | L1 / 无风险 | L1 / 安全常识 | 是 | 否 | 54.24 | 0.3911 |
| fixed_zh | zh | L2-01 | L2 / 安全常识 | L3 / 安全常识 | 否 | 是 | 58.85 | 0.4941 |
| fixed_zh | zh | L2-02 | L2 / 安全常识 | L1 / 安全常识 | 否 | 是 | 58.85 | 0.5355 |
| fixed_zh | zh | L2-03 | L2 / 异常数值 | L3 / 异常数值 | 否 | 是 | 61.79 | 0.6292 |
| fixed_zh | zh | L2-04 | L2 / 医疗 | L3 / 异常数值 | 否 | 否 | 54.39 | 0.4934 |
| fixed_zh | zh | L2-05 | L2 / 危险行为 | L3 / 无风险 | 否 | 否 | 54.58 | 0.4512 |
| fixed_zh | zh | L2-06 | L2 / 安全常识 | L1 / 无风险 | 否 | 否 | 56.95 | 0.5268 |
| fixed_zh | zh | L2-07 | L2 / 异常数值 | L3 / 异常数值 | 否 | 是 | 55.03 | 0.4643 |
| fixed_zh | zh | L2-08 | L2 / 医疗 | L3 / 安全常识 | 否 | 否 | 54.48 | 0.5575 |
| fixed_zh | zh | L3-01 | L3 / 医疗 | L3 / 医疗 | 是 | 是 | 53.79 | 0.7508 |
| fixed_zh | zh | L3-02 | L3 / 医疗 | L3 / 异常数值 | 是 | 否 | 54.65 | 0.6112 |
| fixed_zh | zh | L3-03 | L3 / 安全常识 | L3 / 医疗 | 是 | 否 | 56.26 | 0.6166 |
| fixed_zh | zh | L3-04 | L3 / 安全常识 | L1 / 安全常识 | 否 | 是 | 52.23 | 0.6203 |
| fixed_zh | zh | L3-05 | L3 / 危险行为 | L3 / 无风险 | 是 | 否 | 53.84 | 0.3993 |
| fixed_zh | zh | L3-06 | L3 / 危险行为 | L3 / 无风险 | 是 | 否 | 53.96 | 0.5658 |
| fixed_zh | zh | L3-07 | L3 / 异常数值 | L3 / 异常数值 | 是 | 是 | 56.33 | 0.6423 |
| fixed_zh | zh | L3-08 | L3 / 异常数值 | L3 / 无风险 | 是 | 否 | 59.14 | 0.6751 |
| fixed_zh | zh | L4-01 | L4 / 医疗 | L3 / 医疗 | 否 | 是 | 63.58 | 0.7869 |
| fixed_zh | zh | L4-02 | L4 / 医疗 | L3 / 异常数值 | 否 | 否 | 52.94 | 0.5129 |
| fixed_zh | zh | L4-03 | L4 / 危险行为 | L3 / 危险行为 | 否 | 是 | 59.41 | 0.7512 |
| fixed_zh | zh | L4-04 | L4 / 危险行为 | L3 / 危险行为 | 否 | 是 | 51.12 | 0.8011 |
| fixed_zh | zh | L4-05 | L4 / 异常数值 | L3 / 异常数值 | 否 | 是 | 54.17 | 0.5871 |
| fixed_zh | zh | L4-06 | L4 / 异常数值 | L3 / 异常数值 | 否 | 是 | 52.58 | 0.8379 |
| fixed_zh | zh | L4-07 | L4 / 安全常识 | L1 / 安全常识 | 否 | 是 | 57.13 | 0.4775 |
| fixed_zh | zh | L4-08 | L4 / 安全常识 | L3 / 危险行为 | 否 | 否 | 52.85 | 0.8415 |
| blind_zh | zh | B-L1-01 | L1 / 无风险 | L3 / 无风险 | 否 | 是 | 53.42 | 0.4936 |
| blind_zh | zh | B-L1-02 | L1 / 无风险 | L1 / 无风险 | 是 | 是 | 54.03 | 0.6242 |
| blind_zh | zh | B-L1-03 | L1 / 无风险 | L3 / 无风险 | 否 | 是 | 63.80 | 0.3503 |
| blind_zh | zh | B-L1-04 | L1 / 无风险 | L3 / 无风险 | 否 | 是 | 53.23 | 0.5750 |
| blind_zh | zh | B-L1-05 | L1 / 无风险 | L3 / 无风险 | 否 | 是 | 54.28 | 0.4899 |
| blind_zh | zh | B-L1-06 | L1 / 无风险 | L3 / 安全常识 | 否 | 否 | 66.34 | 0.4849 |
| blind_zh | zh | B-L1-07 | L1 / 无风险 | L3 / 无风险 | 否 | 是 | 61.14 | 0.4493 |
| blind_zh | zh | B-L1-08 | L1 / 无风险 | L2 / 无风险 | 否 | 是 | 51.71 | 0.5057 |
| blind_zh | zh | B-L2-01 | L2 / 安全常识 | L3 / 无风险 | 否 | 否 | 51.82 | 0.4445 |
| blind_zh | zh | B-L2-02 | L2 / 安全常识 | L3 / 无风险 | 否 | 否 | 53.58 | 0.4360 |
| blind_zh | zh | B-L2-03 | L2 / 异常数值 | L3 / 异常数值 | 否 | 是 | 56.93 | 0.6719 |
| blind_zh | zh | B-L2-04 | L2 / 医疗 | L3 / 无风险 | 否 | 否 | 52.70 | 0.5271 |
| blind_zh | zh | B-L2-05 | L2 / 危险行为 | L3 / 无风险 | 否 | 否 | 58.71 | 0.4532 |
| blind_zh | zh | B-L2-06 | L2 / 安全常识 | L1 / 安全常识 | 否 | 是 | 62.82 | 0.5503 |
| blind_zh | zh | B-L2-07 | L2 / 异常数值 | L1 / 异常数值 | 否 | 是 | 53.11 | 0.4112 |
| blind_zh | zh | B-L2-08 | L2 / 医疗 | L1 / 无风险 | 否 | 否 | 52.04 | 0.5777 |
| blind_zh | zh | B-L3-01 | L3 / 医疗 | L3 / 医疗 | 是 | 是 | 50.52 | 0.5905 |
| blind_zh | zh | B-L3-02 | L3 / 医疗 | L3 / 医疗 | 是 | 是 | 52.38 | 0.7570 |
| blind_zh | zh | B-L3-03 | L3 / 安全常识 | L3 / 无风险 | 是 | 否 | 52.98 | 0.5361 |
| blind_zh | zh | B-L3-04 | L3 / 危险行为 | L3 / 无风险 | 是 | 否 | 52.35 | 0.5671 |
| blind_zh | zh | B-L3-05 | L3 / 危险行为 | L1 / 无风险 | 否 | 否 | 53.60 | 0.4761 |
| blind_zh | zh | B-L3-06 | L3 / 异常数值 | L3 / 异常数值 | 是 | 是 | 56.55 | 0.3702 |
| blind_zh | zh | B-L3-07 | L3 / 医疗 | L3 / 医疗 | 是 | 是 | 54.66 | 0.6929 |
| blind_zh | zh | B-L3-08 | L3 / 安全常识 | L1 / 安全常识 | 否 | 是 | 53.44 | 0.5744 |
| blind_zh | zh | B-L4-01 | L4 / 医疗 | L3 / 无风险 | 否 | 否 | 52.50 | 0.4397 |
| blind_zh | zh | B-L4-02 | L4 / 医疗 | L3 / 异常数值 | 否 | 否 | 56.88 | 0.4639 |
| blind_zh | zh | B-L4-03 | L4 / 危险行为 | L3 / 危险行为 | 否 | 是 | 53.14 | 0.5800 |
| blind_zh | zh | B-L4-04 | L4 / 危险行为 | L3 / 危险行为 | 否 | 是 | 50.95 | 0.6296 |
| blind_zh | zh | B-L4-05 | L4 / 异常数值 | L3 / 异常数值 | 否 | 是 | 52.06 | 0.6924 |
| blind_zh | zh | B-L4-06 | L4 / 异常数值 | L3 / 异常数值 | 否 | 是 | 56.61 | 0.8971 |
| blind_zh | zh | B-L4-07 | L4 / 安全常识 | L3 / 安全常识 | 否 | 是 | 53.97 | 0.6201 |
| blind_zh | zh | B-L4-08 | L4 / 安全常识 | L3 / 无风险 | 否 | 否 | 54.60 | 0.5486 |
| fixed_en | en | L1-01 | L1 / no risk | L1 / no risk | 是 | 是 | 58.09 | 0.5345 |
| fixed_en | en | L1-02 | L1 / no risk | L2 / abnormal measurement | 否 | 否 | 51.50 | 0.6731 |
| fixed_en | en | L1-03 | L1 / no risk | L2 / safety knowledge | 否 | 否 | 59.38 | 0.4179 |
| fixed_en | en | L1-04 | L1 / no risk | L1 / safety knowledge | 是 | 否 | 54.27 | 0.9161 |
| fixed_en | en | L1-05 | L1 / no risk | L2 / safety knowledge | 否 | 否 | 63.72 | 0.7148 |
| fixed_en | en | L1-06 | L1 / no risk | L1 / safety knowledge | 是 | 否 | 58.58 | 0.4211 |
| fixed_en | en | L1-07 | L1 / no risk | L1 / safety knowledge | 是 | 否 | 59.86 | 0.4928 |
| fixed_en | en | L1-08 | L1 / no risk | L1 / safety knowledge | 是 | 否 | 64.64 | 0.8424 |
| fixed_en | en | L2-01 | L2 / safety knowledge | L2 / medical | 是 | 否 | 56.09 | 0.4990 |
| fixed_en | en | L2-02 | L2 / safety knowledge | L1 / safety knowledge | 否 | 是 | 69.16 | 0.5281 |
| fixed_en | en | L2-03 | L2 / abnormal measurement | L1 / abnormal measurement | 否 | 是 | 59.62 | 0.5238 |
| fixed_en | en | L2-04 | L2 / medical | L1 / safety knowledge | 否 | 否 | 54.87 | 0.6374 |
| fixed_en | en | L2-05 | L2 / dangerous behavior | L1 / safety knowledge | 否 | 否 | 72.86 | 0.6661 |
| fixed_en | en | L2-06 | L2 / safety knowledge | L1 / safety knowledge | 否 | 是 | 57.92 | 0.5866 |
| fixed_en | en | L2-07 | L2 / abnormal measurement | L2 / abnormal measurement | 是 | 是 | 52.64 | 0.5994 |
| fixed_en | en | L2-08 | L2 / medical | L2 / safety knowledge | 是 | 否 | 61.59 | 0.4342 |
| fixed_en | en | L3-01 | L3 / medical | L2 / medical | 否 | 是 | 53.49 | 0.6652 |
| fixed_en | en | L3-02 | L3 / medical | L2 / abnormal measurement | 否 | 否 | 59.48 | 0.4231 |
| fixed_en | en | L3-03 | L3 / safety knowledge | L1 / medical | 否 | 否 | 63.00 | 0.4837 |
| fixed_en | en | L3-04 | L3 / safety knowledge | L2 / safety knowledge | 否 | 是 | 57.70 | 0.6037 |
| fixed_en | en | L3-05 | L3 / dangerous behavior | L1 / safety knowledge | 否 | 否 | 63.10 | 0.9272 |
| fixed_en | en | L3-06 | L3 / dangerous behavior | L2 / safety knowledge | 否 | 否 | 54.24 | 0.5099 |
| fixed_en | en | L3-07 | L3 / abnormal measurement | L1 / abnormal measurement | 否 | 是 | 63.62 | 0.6560 |
| fixed_en | en | L3-08 | L3 / abnormal measurement | L2 / abnormal measurement | 否 | 是 | 65.94 | 0.4413 |
| fixed_en | en | L4-01 | L4 / medical | L4 / medical | 是 | 是 | 82.92 | 0.7308 |
| fixed_en | en | L4-02 | L4 / medical | L2 / medical | 否 | 是 | 61.97 | 0.4212 |
| fixed_en | en | L4-03 | L4 / dangerous behavior | L1 / dangerous behavior | 否 | 是 | 62.81 | 0.3731 |
| fixed_en | en | L4-04 | L4 / dangerous behavior | L1 / dangerous behavior | 否 | 是 | 53.17 | 0.4311 |
| fixed_en | en | L4-05 | L4 / abnormal measurement | L2 / abnormal measurement | 否 | 是 | 65.05 | 0.6478 |
| fixed_en | en | L4-06 | L4 / abnormal measurement | L1 / abnormal measurement | 否 | 是 | 55.44 | 0.6179 |
| fixed_en | en | L4-07 | L4 / safety knowledge | L2 / safety knowledge | 否 | 是 | 59.65 | 0.9791 |
| fixed_en | en | L4-08 | L4 / safety knowledge | L2 / safety knowledge | 否 | 是 | 55.99 | 0.4904 |
