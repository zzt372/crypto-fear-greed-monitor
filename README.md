# Crypto Fear & Greed Monitor

[![Update Crypto Fear & Greed](https://github.com/zzt372/crypto-fear-greed-monitor/actions/workflows/update-fng.yml/badge.svg)](https://github.com/zzt372/crypto-fear-greed-monitor/actions/workflows/update-fng.yml)

Alternative.me の **Crypto Fear & Greed Index** を GitHub Actions で定期取得し、検証済みの最新値を `latest.json` として公開する小さなモニターです。

このリポジトリの目的は、ChatGPT など外部の監視処理が Alternative.me へ直接アクセスできない場合でも、**Alternative.me 公式 API 由来の値だけ**を安定して参照できるようにすることです。

> **Data source:** [Alternative.me Crypto Fear & Greed Index](https://alternative.me/crypto/fear-and-greed-index/)  
> **Official API:** `https://api.alternative.me/fng/`

このリポジトリは Alternative.me の公式プロジェクトではありません。Fear & Greed Index のデータは Alternative.me に帰属します。

## 仕組み

```text
Alternative.me official API
          ↓
     GitHub Actions
          ↓
  fetch_fng.py で検証
          ↓
      latest.json
          ↓
   ChatGPT / 外部監視
```

GitHub Actions が毎時 Alternative.me 公式 API を取得し、`fetch_fng.py` でレスポンスを検証します。

検証に成功した場合だけ `latest.json` を更新します。API 取得失敗やデータ異常があった場合は Workflow を失敗させ、**既存の `latest.json` を上書きしません**。

## 更新頻度

Workflow は毎時 **7分（UTC）** に実行します。

```yaml
schedule:
  - cron: "7 * * * *"
```

GitHub Actions は毎時ちょうどの時間帯に負荷が集中して遅延する場合があるため、0分ではなく7分にずらしています。

`workflow_dispatch` にも対応しているため、GitHub の **Actions → Update Crypto Fear & Greed → Run workflow** から手動実行できます。

## データ検証

`latest.json` に採用する前に、少なくとも次を検証します。

- HTTP リクエストが成功している
- レスポンスが JSON として解析できる
- `metadata.error` にエラーがない
- `data[0]` が存在する
- `value` が 0〜100 の整数
- `value_classification` が既知の分類名
- `value` と `value_classification` の組み合わせが整合している
- `timestamp` が Unix time として解釈できる
- `timestamp` が未来ではない
- `timestamp` が取得時点から48時間以上古くない

カテゴリの整合性チェックには次の区分を使用します。

| Value | Classification |
|---:|---|
| 0–24 | Extreme Fear |
| 25–44 | Fear |
| 45–55 | Neutral |
| 56–75 | Greed |
| 76–100 | Extreme Greed |

## `latest.json`

最新の検証済みデータは次の URL から取得できます。

```text
https://raw.githubusercontent.com/zzt372/crypto-fear-greed-monitor/main/latest.json
```

出力例:

```json
{
  "ok": true,
  "value": 65,
  "value_classification": "Greed",
  "timestamp": 1787702400,
  "timestamp_iso": "2026-08-26T00:00:00Z",
  "fetched_at": "2026-08-26T07:40:33.174624Z",
  "source": "Alternative.me official API",
  "endpoint": "https://api.alternative.me/fng/?limit=1&format=json"
}
```

### フィールド

| Field | 内容 |
|---|---|
| `ok` | 検証済み正常データであることを示すフラグ |
| `value` | Fear & Greed Index の値（0〜100） |
| `value_classification` | `Extreme Fear` / `Fear` / `Neutral` / `Greed` / `Extreme Greed` |
| `timestamp` | Alternative.me 公式 API が返した Unix timestamp |
| `timestamp_iso` | `timestamp` の UTC ISO 8601 表記 |
| `fetched_at` | GitHub Actions が取得・検証した時刻 |
| `source` | データソース識別子 |
| `endpoint` | 実際に取得した Alternative.me 公式 API endpoint |

外部監視で利用する場合は、`value` だけではなく **`fetched_at` と `timestamp` の鮮度も確認することを推奨**します。

## 障害時の挙動

API 取得には最大3回の試行を行います。

```text
1回目失敗
  ↓
待機して再試行
  ↓
2回目失敗
  ↓
待機して再試行
  ↓
3回目失敗
  ↓
Workflow failure
  ↓
latest.json は変更しない
```

これにより、一時的な DNS 障害、タイムアウト、HTTP エラー、壊れた JSON などが発生しても、不正な値で正常データを上書きしないようにしています。

## ファイル構成

```text
.
├── .github/
│   └── workflows/
│       └── update-fng.yml   # 定期取得・commit
├── fetch_fng.py             # API取得・検証・JSON生成
├── latest.json              # 最新の検証済み値
└── README.md
```

## ローカル実行

Python 3.12 以降を推奨します。外部ライブラリは使用していません。

```bash
python fetch_fng.py
```

正常なら `latest.json` が更新され、標準出力にも取得結果が表示されます。

異常時は終了コード `1` で終了し、既存の `latest.json` は保持されます。

## GitHub Actions の権限

Workflow は生成した `latest.json` を同じリポジトリへ commit するため、次の権限を使用します。

```yaml
permissions:
  contents: write
```

Secrets や API キーは不要です。Alternative.me Fear & Greed Index API は公開 GET API を利用しています。

## データ利用について

Alternative.me は Fear & Greed Index API の利用時に、データソースとして Alternative.me を明示することを求めています。このリポジトリでも `source` フィールドと README の双方で出典を明記しています。

詳細は Alternative.me の公式ページを確認してください。

- https://alternative.me/crypto/fear-and-greed-index/
- https://api.alternative.me/fng/

## 注意事項

- このリポジトリは投資助言を提供するものではありません。
- 指標の定義・算出方法・提供状況は Alternative.me 側で変更される可能性があります。
- GitHub Actions の `schedule` は厳密なリアルタイム実行を保証するものではなく、GitHub 側の混雑などにより遅延する場合があります。
- `latest.json` を利用する側でも `fetched_at` の鮮度検証を行うことを推奨します。
