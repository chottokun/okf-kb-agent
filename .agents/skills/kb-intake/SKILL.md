---
name: KB Intake
description: Run the single intake gate for OKF knowledge growth — collect candidate proposals from the three routes plus the enrichment axis, verify them factually with okf_candidate_check, and hand selected units to the build queue with proposer and selector kept separate.
trigger_conditions:
  - intake
  - candidate proposal
  - 候補提案
  - 取り込み候補
  - 取り込み判定
  - proposal inbox
  - 増補候補
---

# KB Intake

## 1. 原則

> 入口は複数、関門は1つ。道具は事実だけを返し、優先順位は判断の層で都度つける。

- すべての候補は proposal inbox → intake ゲート → queue の順に合流する。どのルートの候補も例外なく同じ関門を通る。
- **提案者 ≠ 選定者**。提案した者（エージェント）が自分の提案を採用しない。
- 候補生成の実行者の権限は「読み取り＋提案まで」。キュー投入は選定者の行為として分ける。
- 道具（`okf_candidate_check` / `okf_links` 等）の出力は重みを持たない事実であり、採否と優先順位の根拠にはするが、判定そのものとして扱わない。

## 2. 入口（3ルート＋深さの軸）

### ルート1：KB 内側のシグナル

KB 自身の状態から欠けの事実を列挙する。

- `okf_links`：到達不能・孤立・inbound ゼロの概念。
- 概念ノートが無いのに複数ノートの本文に頻出する用語（同義語グループ解決後の残差）。`okf_search` / `okf_traverse` と本文の読みで裏を取る。
- 既存概念の出典が参照するのに未収録のトピック。
- 出力は「用語／出現箇所／近接する既存概念」の事実リスト。提示範囲（閾値）は調整であって重要度の判定として返さない。

### ルート2：外側のシグナル（新着）

- **段階1（指示による調査）**：テーマ（キーワード、対象 KB、期間の目安）を与えて arXiv / EPO OPS 等の一次ソースを調べる。新規性は既存 KB との突合で事実として示す（既収録／未収録、近接概念）。出力は候補リスト（識別子、タイトル、既存 KB との関係）。
- **段階2（定期監視）**：段階1の調査をスケジュールに載せたもの。監視テーマと頻度は段階1の運用実績を見て決める（未決の間は段階1のみ）。

### ルート3：議論の中から

会話の中で候補が浮上したら、その場で proposal を1枚置く。来歴はその議論自体（日時とチャットのポインタ）。新しい道具は作らない。

拾う条件は次の3つ。いずれかに当たれば信号として扱う：

- 識別子（arXiv ID、DOI、特許番号等）つきの論文・特許・資料が会話に出た。
- 既存ノートの主張への訂正・続き・新しい裏付けが会話に出た。
- のぶひこ／BlackClaw／シャナのいずれかが「入れたい／残したい」と口にした。

扱いは従来どおり：候補はそのままユニットにせず、§4 の intake ゲート（candidate-check＋出典確認）を通してからユニット化する。会話の全てを intake 化しない——信号の出た所だけを拾うのがこのルートの型である。

その場で拾い切れなかった信号は、日次回収（cron `kb-conversation-capture-daily`、毎日 21:30）が当日の会話を振り返って回収する。

### 深さの軸：既存概念の増補（enrichment）

新規概念とは直交する軸。入口はルート1のシグナルが兼ねる：被リンク数が多いのに出典が薄いハブ、ノートが小さい、`verified` イベントが古い（または未検証）、新しい追補・対抗論文の出現（ルート2からも入る）。

- 増補の中身：出典を対象 KB のプロファイル基準へ寄せて再接地（paper-centric KB では定義論文1＋追補・対抗2＝3本が基準）、数値と条件を読んだ版に揃える、リンクの双方向補完、再検証後の `verified` イベント追記（`generated` の更新と合わせて）。
- ユニット種別は `enrichment` として新規構築と区別する。監査は差分型（変更・追加された claims のみ照合）になる（`kb-audit` 参照）。

## 3. Proposal の書式

書式は本スキルが定義する：ヘッダ（`proposer` / `date` / `kb` / `slug` / `title` / `origin`＝指示の文脈と一次ソースの識別子。`strand/<name>` 形式のタグは対象 KB のプロファイルが持つ場合のみ）＋ `gap-axis`（既存ノートに対する欠けの軸）＋隣接性（直接の接続と拡張の仕方）＋ KB 内での浮上（既存ノートからの引用を出典ノート名つきで。無ければ `taxonomy-gap` と明示）。候補タグを付与する際は**タグ正規化規則**に従う（名前空間区切りは `/` でコロン `:` は使わない、`.` は `-` へ置換、大文字小文字は維持、空白なし、正規化衝突は自動解消せず人間へエスカレーション）。なお、`okf_candidate_check` の verbatim 照合（check_proposal）が解析できるのは、slug 見出しに `(b) Primary-Source Emergence` の引用行を伴う候補プール形式である。verbatim 照合にかけたい proposal はその形式で書く。

## 4. Intake ゲートの手順

1. **受け付け**：proposal を inbox に置く（ルートを問わず同じ置き場・同じ書式）。
2. **事実確認**：`okf_candidate_check` で slug の占有、同義語グループへの所属、タグ来歴を確認する。`candidates` と `proposal` を併用した場合、proposal は inputs の状態記録にのみ使われ verbatim 照合は走らない。verbatim 照合は、解析可能な形式で書かれた proposal を単独で渡したとき（check_proposal）に実行される。結果は事実として proposal に添える。
3. **選定**：提案者以外の選定者が採否を決め、採用分に優先順位をつける。優先順位はこの層でのみつける（道具の出力順や件数を順位として流用しない）。
4. **キュー投入**：採用分を構築ユニット化して queue へ渡す（変換と queue の管理はハーネス層。ユニットには対象 KB、`kind`（new / enrichment）、出典識別子を持たせる）。候補レコードおよびそこから構築されるノートは、最初から OKF v0.3 のエントリ形式 `sources`（`id`, `resource`, 任意の `title`, `x-okfkb-*`）と `generated: {by, at}`、および正規化済みタグ（`strand/<name>` 等）を使用する。
5. **不採用の記録**：不採用分も理由とともに inbox に残す。再提案は新しい事実が付いた場合のみ。

## 5. 委譲先の明示

- バッチ単位の候補選定・収集運営・報告 → `.agents/skills/kb-batch-discipline/SKILL.md`
- 監査と昇格ゲート → `.agents/skills/kb-audit/SKILL.md`
- ノート構造・検索・リンク診断の使い方 → `.agents/skills/okf-wiki/SKILL.md`
- 出典の検証と取得 → `.agents/skills/source-verify/SKILL.md`
