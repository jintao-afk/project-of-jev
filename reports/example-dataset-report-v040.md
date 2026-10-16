# 本地数据分析报告

任务：分析两份历史运行记录，比较耗时和状态分布，检查超过阈值的记录，生成可核查报告。

依据：声明字段与源文件；数值保留六位小数。状态计数不代表答案正确。

## baseline.csv

源文件SHA256：`083fae9ed3c706620f056810e6196ccf87a4701043808f87c6b30ac5daf7d08d`
数值字段：total\_ms

| 指标 | 数值 |
|---|---:|
| 全部记录 | 16 |
| 有效数值记录 | 16 |
| 缺失数值 | 0 |
| 非法数值 | 0 |
| 最小值 | 111.230000 |
| 最大值 | 36848.040000 |
| 均值 | 3274.656875 |
| 中位数 | 690.345000 |

缺失行：[]
非法值行：[]

### 状态字段原始计数

| 状态 | 条数 |
|---|---:|
| completed | 1 |
| needs\_review | 11 |
| stopped | 4 |

## current.csv

源文件SHA256：`05e7a3f8e44d69287044c07162564847304de4692b4b5a962551dc9277cc25c6`
数值字段：total\_ms

| 指标 | 数值 |
|---|---:|
| 全部记录 | 16 |
| 有效数值记录 | 16 |
| 缺失数值 | 0 |
| 非法数值 | 0 |
| 最小值 | 0.440000 |
| 最大值 | 12628.410000 |
| 均值 | 1821.498750 |
| 中位数 | 1080.150000 |

缺失行：[]
非法值行：[]

### 状态字段原始计数

| 状态 | 条数 |
|---|---:|
| completed | 1 |
| needs\_review | 13 |
| stopped | 2 |

## 阈值检查（严格大于）

```json
{
  "baseline.csv": {
    "operator": "\u003e",
    "threshold": "2000",
    "count": 3,
    "matches": [
      {
        "source_row": 2,
        "value": "36848.04"
      },
      {
        "source_row": 11,
        "value": "2221.94"
      },
      {
        "source_row": 16,
        "value": "4780.64"
      }
    ],
    "missing_rows": [],
    "invalid_rows": []
  },
  "current.csv": {
    "operator": "\u003e",
    "threshold": "2000",
    "count": 3,
    "matches": [
      {
        "source_row": 2,
        "value": "12628.41"
      },
      {
        "source_row": 7,
        "value": "2699.74"
      },
      {
        "source_row": 16,
        "value": "2236.75"
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
  "mean_delta": "-1453.158125",
  "status_counts": {
    "baseline.csv": {
      "completed": 1,
      "needs_review": 11,
      "stopped": 4
    },
    "current.csv": {
      "completed": 1,
      "needs_review": 13,
      "stopped": 2
    }
  },
  "scope": "第二份减第一份的描述性差异；样本或负载可能不同，不证明因果、性能优势或答案质量。"
}
```

## 验收范围

结构化CSV分析条件；不自动验证自然语言额外要求或模型建议，不将状态计数视为答案正确率。
