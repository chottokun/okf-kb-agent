---
name: KB Search
description: Iterative OKF knowledge-base retrieval discipline combining anchor acquisition, bounded graph neighbor inspection (okf neighbors / okf_neighbors), path and link-context reading, and growth-candidate handoff when dictionary or link gaps block retrieval.
trigger_conditions:
  - kb-search
  - 検索の作法
  - 近傍検索
  - neighbors
  - okf_neighbors
  - 関係検索
  - アンカー
---

# KB Search — 道具の裁量を支える検索の作法

## 1. 基本前提

> **検索は一発で回答を当てる作業ではない。**

KB 検索は「**アンカーを掴む → 近傍と経路を見る → ノートを読んで判断する**」という反復ループで行う。
道具（`okf search` / `okf neighbors` / MCP の `okf_search` / `okf_neighbors`）は客観的な構造・一致・経路・文脈を返すだけで、重みや勝敗の判定は持たない。決めるのは常に読み手（エージェント／人間）の判断である。

## 2. ループの手順

### ステップ 1：アンカーを掴む

1. **第一候補（概念名・辞書一致）**：概念名・スラッグ・`synonyms.json` に載る別名で引けるなら、それをアンカーとして確定する（`okf search <wiki> "<term>"`、必要なら `--type concept` や `--expand` を併用）。
2. **第二候補（キーワード／セマンティックの Top-1）**：語彙一致や言い換えクエリでは、`okf search`（または利用可能な探索面の Top-1）を暫定アンカー候補とする。
3. **固定できなければ広げない**：アンカーの確度が低い・無関係なノードしか出ない状態でグラフ走査へ進まない。**間違ったアンカーからの拡張は誤りを増幅する。** クエリの語を絞るか、対象概念の不在を疑う。

### ステップ 2：近傍と経路を引く（`hops` と `top_n` の裁量）

アンカー概念そのものではなく「関係するもの・比較対象・直交手法・前提概念」が欲しいときは `okf neighbors`（MCP: `okf_neighbors`）を呼ぶ。

- **`hops` の作法**：
  - **必ず `hops=1`（既定）から始める。**
  - `hops` を `2` 以上に広げるのは、(1) 1 hop の近傍に問いの答えの形が見当たらないとき、(2) 候補が割れて 2 hop 先の中継や別経路で確かめたいとき、に限る。
  - **KB の密度を意識する**：小〜中規模 KB（例：概念 40〜55 件・平均両方向次数 約 10）では、`hops=2` でほぼ KB 全体に届く。`hops` を増やすことは「絞るか否か」そのものの選択であり、KB 規模が大きくなれば適切な目安も変わる（上限は道具側で `3` に切り詰められる）。
- **`top_n` の作法**：
  - 既定は `10`（上限 `50`）。
  - 1 hop 内に同率・多数の隣接があり候補が割れるときは `top_n` を広げて全体を見渡す。答えの根拠が揃ったらそれ以上広げずに止める。
  - 広げること自体は悪ではないが、判断材料にならない行を増やすだけならノイズになる。
- **`direction` の作法**：
  - 関係性の方向（自分が参照している概念か、自分を参照している概念か）を問わず探す既定は `both`。前提の参照元を辿るときは `out`、被参照・応用先を見るときは `in` を選ぶ。

```bash
# CLI: まずは 1 hop でアンカーの直接近傍とリンク文脈を確認する
uv run okf neighbors <wiki> <anchor> --hops 1 --direction both --top-n 10 --json

# 1 hop に答えが無い／候補が割れる場合のみ 2 hop へ広げる
uv run okf neighbors <wiki> <anchor> --hops 2 --direction both --top-n 20 --json
```

### ステップ 3：経路とリンク文脈を読んで判断する

`okf neighbors` / `okf_neighbors` の出力にある `path` と `link_contexts` は、単なる順位スコアではなく**関係性の証拠**である。

- **`path`（`A -> B -> C`）**：どの概念を経由して届いたかを根拠として示す。
- **`link_contexts`**：そのリンクがノートのどの見出し（`heading`）の下で、どのような文脈行（`context`）として張られているかを読む。「なぜ結ばれているか（直交・競合・前提・拡張・適用）」を文脈から読み取って採用／却下を決める。
- 候補を絞れたら対象ノートの該当節・全文を読み、最終判断を下す（`okf_context` 相当のトークン予算を守る）。

## 3. 止めどきと「見つからないとき」の扱い

- **答えが確定したら止める**：選んだ概念ノートと `path` / `link_contexts` で問いへの根拠が揃った時点で探索を打ち切る。
- **アンカー不在／リンク未到達を道具の失敗で終わらせない**：
  - `synonyms.json` に別名・表記揺れが無くアンカーを掴めなかった場合 → **辞書の穴候補**として記録する。
  - アンカーは掴めたが `hops=1〜2` で期待する概念へ到達できない、あるいは `found: true` でも本来あるべき概念間にリンクが無い場合 → **リンク不足・概念不足候補**として記録する。
  - これらは握り潰さず、`.agents/skills/kb-intake/SKILL.md` の入口ルート（ルート 1：KB 内側のシグナル、またはルート 3：議論・利用中のギャップ発見）へ接続し、KB 成長候補として回す。

## 4. 関連スキル

- 全体運用・他コマンド・スコアリング詳細 → `.agents/skills/okf-wiki/SKILL.md`
- 見つかった欠け（辞書・リンク・未収録概念）の提案化 → `.agents/skills/kb-intake/SKILL.md`
