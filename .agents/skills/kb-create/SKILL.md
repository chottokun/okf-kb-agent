---
name: KB Create
description: Create a new OKF knowledge base end to end — fix the frame decisions with the owner, scaffold with okf init on the Drive home, seed under Stage-1 full verification, then wire the new KB into sync, catalog, queue conversion, and the viewer refresh so the growth loop can reach it.
trigger_conditions:
  - 新規KB
  - KB作成
  - KB立ち上げ
  - new KB
  - create a knowledge base
---

# KB Create — 新しい KB を作る流れ

概念の追加は kb-intake の仕事。このスキルは **KB そのものの新設**を扱う。部品（`okf init`、設計規約、バッチ規律）は既にあるので、ここではそれらを一続きの手順に繋ぎ、配線の抜けを防ぐ。

## 0. フレーム決定（オーナーと決める）

次は形そのものの決定なので、オーナー（のぶひこ）の判断を先に受ける。決まった後の作業は機械的に進めてよい。

- **slug**: `kb-<name>` 形式（lowercase kebab）。
- **形／プロファイル**: paper-centric／patent-centric／ops-record のどれか（判断材料は `okf-design-conventions` と `kb-batch-discipline/references/` の各プロファイル）。
- **対象範囲と種の規模**: 何を扱う KB か、最初の種を何件程度にするか。
- **ダッシュボード配布**: Drive `dashboard/<kb>/` の2点セット（単独HTML＋export JSON）の対象にするかどうか。

## 1. 骨格（Drive ホームに作る）

KB の原本は Drive の OKF ルート直下に置く（新しい KB は Drive で生まれるのが既定）。

1. Drive 側に `<slug>/` を作り、サードのマウント（`~/okf-drive/<slug>`）から見えることを確認する。
2. `okf init <dir>` で index／log／エージェントガイドを生成する。
3. プロファイルに従い `concepts/` と証跡の置き場（`evidence/` 配下の構成、共有キャッシュ型かどうか）を用意する。証跡運用は KB の型で決まる（kb-audit の証跡節と `okf-design-conventions` §3・§7）。

## 2. 種の投入（Stage 1 全件検証）

新しいドメインの KB は `kb-batch-discipline` の **Stage 1: Full Verification** で種を入れる：staging で起草し、トピック外ノードを除き、ゲート全緑（validate／index --check／links）を確認し、全ノートを出典と照合してから本番へ merge する。昇格後の運用は通常の成長ループ（kb-intake → 構築 → kb-audit）に移る。

## 3. 配線チェックリスト

新 KB を既存の仕組みが拾えるよう、次をすべて行う（1つでも欠けると、その経路から KB が見えなくなる）。

1. **Hermes 同期**: `services/okf-mcp/sync_okf.sh` の `KBS` に slug を追加する（本番コピーと staging の読み取り同期の対象になる）。
2. **カタログ**: 同 `gen_catalog.py` の `KBS` に slug を追加し、カタログを再生成する（BlackClaw はカタログ経由で KB を認識する）。
3. **キュー変換**: ハーネス側 `proposal_to_unit.py` の `KB_PREFIX` に接頭辞（例: `semi`／`ai`／`ops` と重ならない短い接頭辞）を追加する。
4. **ビューア更新**: ハーネス側 `dashboard/refresh_all.sh` の export 対象と合本の順序に slug を追加する（export のソースは本番コピー。staging は未昇格分を含むので使わない）。
5. **ダッシュボード配布**（§0 で対象と決めた場合のみ）: Drive `dashboard/<slug>/` を用意し、ビューアで単独HTMLを生成できる状態にする。
6. **MCP**: okf-mcp は同期済みコピーをそのまま読むため、ツール側の追加作業はない。

## 4. 疎通確認

- 本番 KB で validate／index --check／links が通る。
- ビューアの合本 export に新しい KB が入り、件数が一致する。
- BlackClaw がカタログと MCP 経由で新しい KB を読める。
- 試験 unit を1件キューに流し、staging 構築→監査→昇格の経路が通る（種の投入と兼ねてもよい）。

## 5. 記録

作成を kb-shana-ops に記録する：slug、形／プロファイル、フレーム決定者と日付、種の規模、配布対象かどうか。以後の変更もそこへ追記する。
