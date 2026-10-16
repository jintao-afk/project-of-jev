# 本地数据分析报告

任务：分析CSV附件并生成数据报告

依据：声明字段与源文件；数值保留六位小数。状态计数不代表答案正确。

## baseline.csv

源文件SHA256：`a033f381506e894f44ff824dcf1198b0907723a8ea44c6836aab7d45da5a6af5`
数值字段：latency\_ms

| 指标 | 数值 |
|---|---:|
| 全部记录 | 4 |
| 有效数值记录 | 2 |
| 缺失数值 | 1 |
| 非法数值 | 1 |
| 最小值 | 120.000000 |
| 最大值 | 180.000000 |
| 均值 | 150.000000 |
| 中位数 | 150.000000 |

缺失行：[4]
非法值行：[5]

### 状态字段原始计数

| 状态 | 条数 |
|---|---:|
| bad | 1 |
| missing | 1 |
| ok | 2 |

## current.csv

源文件SHA256：`0db3fc7d61f5cefc132724d8b2a6e93292893f7c017399b240a3e0310b8162f1`
数值字段：latency\_ms

| 指标 | 数值 |
|---|---:|
| 全部记录 | 4 |
| 有效数值记录 | 4 |
| 缺失数值 | 0 |
| 非法数值 | 0 |
| 最小值 | 90.000000 |
| 最大值 | 270.000000 |
| 均值 | 180.000000 |
| 中位数 | 180.000000 |

缺失行：[]
非法值行：[]

### 状态字段原始计数

| 状态 | 条数 |
|---|---:|
| needs\_review | 1 |
| ok | 3 |

## 阈值检查（严格大于）

```json
{
  "baseline.csv": {
    "operator": "\u003e",
    "threshold": "200",
    "count": 0,
    "matches": [],
    "missing_rows": [
      4
    ],
    "invalid_rows": [
      5
    ]
  },
  "current.csv": {
    "operator": "\u003e",
    "threshold": "200",
    "count": 2,
    "matches": [
      {
        "source_row": 4,
        "value": "210"
      },
      {
        "source_row": 5,
        "value": "270"
      }
    ],
    "missing_rows": [],
    "invalid_rows": []
  }
}
```

## 数据对比（第二份减第一份）

```json
{
  "first": "baseline.csv",
  "second": "current.csv",
  "rows_delta": 0,
  "mean_delta": "30.000000",
  "status_counts": {
    "baseline.csv": {
      "bad": 1,
      "missing": 1,
      "ok": 2
    },
    "current.csv": {
      "needs_review": 1,
      "ok": 3
    }
  },
  "scope": "第二份减第一份的描述性差异；样本或负载可能不同，不证明因果、性能优势或答案质量。"
}
```

## 验收范围

结构化CSV分析条件；不自动验证自然语言额外要求或模型建议，不将状态计数视为答案正确率。
