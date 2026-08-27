# Crypto Fear & Greed Monitor

[![Update Crypto Fear & Greed](https://github.com/zzt372/crypto-fear-greed-monitor/actions/workflows/update-fng.yml/badge.svg)](https://github.com/zzt372/crypto-fear-greed-monitor/actions/workflows/update-fng.yml)

Alternative.me の **Crypto Fear & Greed Index** を GitHub Actions で定期取得し、検証済みの最新正常値を `latest.json` として公開するモニターです。

主な目的は、ChatGPTなどの外部監視処理が Alternative.me に直接アクセスできない場合でも、**Alternative.me公式API由来の値だけ**を安定して参照できるようにすることです。

> **Data source:** [Alternative.me Crypto Fear & Greed Index](https://alternative.me/crypto/fear-and-greed-index/)  
> **Official API:** `https://api.alternative.me/fng/`

このリポジトリは Alternative.me の公式プロジェクトではありません。Fear & Greed Index のデータは Alternative.me に帰属します。

## Architecture

```text
Alternative.me official API
          ↓
  urllib + retry
          ↓ failure
   curl + retry fallback
          ↓
     fetch_fng.py
          ↓ validation
      latest.json
          ↓
   ChatGPT / 外部監視
```

取得・JSON解析・検証のすべてに成功した場合だけ `latest.json` をatomicに置き換えます。

一時的なネットワーク障害、DNS障害、HTTPエラー、壊れたJSON、データ異常などが起きた場合は、**最後に成功した `latest.json` をそのまま保持**します。失敗データで正常値を上書きしません。

## 5分ポーリング

GitHub Actionsのscheduled workflowは**5分ごと**に実行します。

```yaml
schedule:
  - cron: "*/5 * * * *"
```

1時間あたり最大12回の取得機会を持たせることで、1回または数回のschedule遅延・drop、一時的なAPI通信失敗が起きても、次の5分枠で自動的に追いつきやすくしています。

`workflow_dispatch` にも対応しているため、GitHubの **Actions → Update Crypto Fear & Greed → Run workflow** から手動実行できます。

## Commit抑制

API取得・検証は5分ごとに行いますが、`fetched_at` の変化だけで毎回commitすると最大288 commit/日になるため、Git履歴の不要な増加を抑えています。

次の変化は即commitします。

- `value_classification` の変化
- Alternative.me公式 `timestamp` の変化
- `ok` / `source` / `endpoint` の変化

上記が変わらない場合は、原則として**1時間ごとのheartbeat commit**だけを残します。

つまり、**API確認は5分ごと、意味のある変化は即時公開、平常時のGit commitは抑制**という設計です。

## API取得の冗長化

公式API以外の値は使用しません。

取得候補は、同じ Alternative.me 公式 `/fng/` endpoint の次のURL表現です。

```text
https://api.alternative.me/fng/?limit=1&format=json
https://api.alternative.me/fng/
```

処理順序は概ね次の通りです。

```text
公式API URL #1
  ├─ urllib attempt 1
  ├─ urllib attempt 2
  ├─ urllib attempt 3
  └─ curl retry fallback
        ↓ failure
公式API URL #2
  ├─ urllib attempt 1
  ├─ urllib attempt 2
  ├─ urllib attempt 3
  └─ curl retry fallback
        ↓ failure
Workflow failure
        ↓
既存 latest.json を保持
```

`curl` 側でも `--retry-all-errors` を使って再試行します。

第三者サイト、検索スニペット、Webページ上の表示値、Firecrawl、proxy値などをAPI値の代替として使用することはありません。

## データ検証

`latest.json` に採用する前に、少なくとも次を検証します。

- HTTP取得に成功する
- レスポンスがJSONとして解析できる
- `metadata` が存在する
- `metadata.error` にエラーがない
- `data[0]` が存在する
- `value` が0〜100の整数
- `value_classification` が既知の公式分類名
- `timestamp` がUnix timeとして解釈できる
- `timestamp` が大幅に未来ではない
- `timestamp` が72時間以上古くない

### Classification

カテゴリは **Alternative.me公式APIが返す `value_classification` を正**として扱います。

許可する値は次の5種類です。

- `Extreme Fear`
- `Fear`
- `Neutral`
- `Greed`
- `Extreme Greed`

ローカル側で独自の数値境界を再計算し、公式classificationとの一致を必須にすることはしていません。提供元が将来分類方法を変更した場合に、監視側の古い境界定義だけを理由として正常データを拒否することを避けるためです。

## `latest.json`

最新の検証済みデータは次から取得できます。

```text
https://raw.githubusercontent.com/zzt372/crypto-fear-greed-monitor/main/latest.json
```

schema version 2 の例:

```json
{
  "schema_version": 2,
  "ok": true,
  "value": 71,
  "value_classification": "Greed",
  "timestamp": 1787788800,
  "timestamp_iso": "2026-08-27T00:00:00Z",
  "fetched_at": "2026-08-27T02:48:48.840280Z",
  "source_age_seconds": 10128,
  "time_until_update": 76272,
  "source": "Alternative.me official API",
  "endpoint": "https://api.alternative.me/fng/?limit=1&format=json",
  "fetch_method": "urllib-attempt-1"
}
```

### Fields

| Field | 内容 |
|---|---|
| `schema_version` | JSON schemaの世代 |
| `ok` | 検証済み正常データであることを示すフラグ |
| `value` | Fear & Greed Index の値（0〜100） |
| `value_classification` | Alternative.me公式APIが返した分類 |
| `timestamp` | Alternative.me公式APIのUnix timestamp |
| `timestamp_iso` | `timestamp` のUTC ISO 8601表記 |
| `fetched_at` | GitHub Actionsが実際に取得・検証したUTC時刻 |
| `source_age_seconds` | 取得時点での公式timestampの経過秒数 |
| `time_until_update` | APIに値がある場合の次回更新までの秒数 |
| `source` | データソース識別子 |
| `endpoint` | 成功したAlternative.me公式API URL |
| `fetch_method` | 成功した取得経路 |

外部監視では `value` だけでなく、`ok`、`source`、`timestamp`、`fetched_at` も確認してください。

## 自動テスト

`test_fetch_fng.py` を用意し、**すべてのGitHub Actions実行でlive API取得より先に回帰テスト**を実行します。

現在は次をテストしています。

1. 正常な公式形式JSONを受理する
2. 0〜100範囲外のvalueを拒否する
3. 未知のclassificationを拒否する
4. `metadata.error` を拒否する
5. 古すぎるtimestampを拒否する
6. 小さな時計ずれを許容する
7. urllibが失敗した場合にcurl fallbackへ移行する

```bash
python -m unittest -v test_fetch_fng.py
```

テストに失敗した場合はlive API取得へ進みません。

## GitHub Actions の処理

Workflowは次の順で処理します。

```text
checkout@v6
   ↓
setup-python@v6 / Python 3.12
   ↓
regression tests
   ↓
live Alternative.me API fetch
   ↓
validation
   ↓
latest.json atomic replace
   ↓
commit suppression check
   ↓
git commit / skip
   ↓
git push
```

Git pushについても、mainが実行中に進んだ場合を考慮して最大3回までrebase + retryします。

Workflow全体には `concurrency` を設定し、`cancel-in-progress: true` によって古い重複実行を引きずりにくくしています。

## 障害時の考え方

このモニターは「毎回必ず成功する」ことではなく、**一時障害を正常データへ波及させず、次の5分実行で自動回復すること**を重視しています。

```text
1回のscheduleがdrop
        ↓
次の5分枠で再実行

API通信が一時失敗
        ↓
urllib retry
        ↓
curl retry fallback
        ↓
それでも失敗
        ↓
last-known-good latest.json を保持
        ↓
次の5分枠で再挑戦
```

そのため、consumer側も1回の取得失敗を重大障害として扱わず、最後の正常値を保持して次回を待つ設計を推奨します。

## ファイル構成

```text
.
├── .github/
│   └── workflows/
│       └── update-fng.yml   # 5分ごとの定期取得・テスト・commit制御
├── fetch_fng.py             # API取得・retry・validation・JSON生成
├── test_fetch_fng.py        # 回帰テスト
├── latest.json              # 最新の検証済み正常値
└── README.md
```

## ローカル実行

Python 3.12 以降を推奨します。Python側は外部パッケージを必要としません。

テスト:

```bash
python -m unittest -v test_fetch_fng.py
```

実取得:

```bash
python fetch_fng.py
```

正常時は `latest.json` が更新され、標準出力にも結果が表示されます。

異常時は終了コード1で終了し、既存の `latest.json` は保持されます。

## GitHub Actions の権限

生成した `latest.json` を同じリポジトリへcommitするため、次の権限だけを明示しています。

```yaml
permissions:
  contents: write
```

SecretsやAlternative.me API keyは不要です。

## Alternative.me API

Alternative.me公式ページでは Fear and Greed Index APIについて次を公開しています。

- Endpoint: `/fng/`
- Method: `GET`
- `limit` のデフォルト: `1`
- `format` のデフォルト: JSON
- date format未指定時のtimestamp: Unix time

詳細:

- https://alternative.me/crypto/fear-and-greed-index/
- https://alternative.me/crypto/api/
- https://api.alternative.me/fng/

## データ利用について

Alternative.me は Fear & Greed Index API利用時にデータソースを明示するよう案内しています。このリポジトリでも `source` フィールドとREADMEの双方でAlternative.meを明記しています。

## 注意事項

- このリポジトリは投資助言を提供するものではありません。
- 外部サービスであるAlternative.meとGitHub Actionsを使う以上、100%の稼働保証はできません。
- GitHub Actionsの`schedule`は厳密な時刻保証ではありません。
- その制約を前提に、5分ごとの冗長実行、retry、fallback、last-known-good保持、回帰テスト、commit抑制で障害耐性と運用性を高めています。
