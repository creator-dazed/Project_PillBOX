# PiLLBOX お薬カレンダー システム構成 README

自動排出なし・飲み忘れを検知して家族に知らせる見守りピルケース。
本ドキュメントはシステム全体のファイル構成・データフロー・信号仕様をまとめたものです。

管理番号: PBX-README-260708A

---

## 1. 全体構成

```
[ラズパイ(カメラ)] → 判定 → [ESP32-C3(音+センサー)] → 報告
                                        ↓
                          [Google スプレッドシート + GAS]
                                        ↓ (gviz / CSV)
                          [Cloudflare Pages ダッシュボード]
                                        ↓
                                  ブラウザ(家族)
```

- **時刻判断はすべてラズパイ(カメラ)が担当**。ESP32は独自の時刻判定を持たず、ラズパイからの合図(0x01〜0x06)で音を鳴らし、GASに報告するだけ。
- データベースは使用せず、Google スプレッドシートを記録先とする。
- ダッシュボードは静的サイト(Cloudflare Pages)。データ取得は Google Visualization API(gviz)経由。

---

## 2. コンポーネント別ファイル構成

### 2-1. ラズパイ(カメラ・AI判定)

| ファイル | 役割 |
|---|---|
| `monitor.py` | メイン監視プログラム。カメラ撮影→AI判定→ESP32へ信号送信 |
| `predict.py`(未アップロード) | AI判定モデル本体(TFLite) |

現行最新管理番号: **PBX-RPI-260708A**

### 2-2. ESP32-C3(センサー・音声)

| ファイル | 役割 |
|---|---|
| `PiLLBOX_MP3_new.ino`(= `setting20_1.ino`と同一内容) | 磁気センサー監視+KT403A MP3再生。ラズパイからの信号(0x01〜0x06)を受けて動作 |

現行最新版: **★17/★18**(二重頭脳問題解消・BELL前奏化)

### 2-3. GAS(Google Apps Script・バックエンド)

| ファイル | 役割 |
|---|---|
| `gas0708.txt` | doGet/doPost・記録処理・通知(メール/LINE)・管理系アクション(パスワード変更等) |

現行最新管理番号: **PBX-GAS-260708C**(★14キープウォーム機能追加)
**機密ファイルにつき、リポジトリ・成果物には同梱しません。**

### 2-4. ダッシュボード(Cloudflare Pages・静的サイト)

配布ZIP: `PillBox.zip`(フラット9ファイル構成)

| ファイル | 役割 | 現行最新管理番号 |
|---|---|---|
| `index.html` | お薬カレンダー本体(カレンダー・本日の服薬状況) | PBX-CAL-260708H |
| `style.css` | 共通スタイル(index/admin共用) | PBX-CSS-260708E |
| `admin.html` | 管理画面(お知らせ時刻設定・パスワード変更・リセット) | PBX-ADM-260708F |
| `admin.css` | 管理画面専用スタイル | PBX-ADM-CSS-260708C |
| `favicon.ico` | ファビコン(16/32/48px) | 圧縮済み(約5KB) |
| `favicon.png` | ファビコン(32×32・PNG) | — |
| `apple-touch-icon.png` | iOSホーム画面アイコン | — |
| `pillbox_logo_b.png` | ヘッダーロゴ | — |
| `_headers` | Cloudflare Pages用HTTPヘッダー設定(no-cache指定等) | — |

デプロイ先: `https://pillbox.cinnamomeus.workers.dev/`

---

## 3. データ保存先(Googleスプレッドシート)

**SS_ID:** `1s6OVEoa-sj_WcDtYzi_TzFXMheD6-zI47n0LuB3-k9M`

| シート名 | 用途 | 列構成 |
|---|---|---|
| `sensor_data`(gid=0) | 記録本体 | A=日時 / B=フタ開閉(open/close) / C=イベント名・時間帯 |
| `setting` | 服薬時刻設定 | A=key / B=hour / C=minute / D=label |

---

## 4. 信号(バイト)と動作の対応表

ラズパイ(monitor.py)→ESP32→GAS→ダッシュボードの一気通貫の対応。

| バイト | 用途 | ESP32が鳴らす音源 | GASへ送るevent | ダッシュボード反映 |
|---|---|---|---|---|
| 0x01 | 朝2回目アラート | BELL(0004)→0003 | missed_morning | 飲み忘れ(×)・通知 |
| 0x02 | 夜2回目アラート | BELL(0004)→0003 | missed_evening | 飲み忘れ(×)・通知 |
| 0x03 | リマインダー | BELL(0004)→0003 | reminder | 表示しない(催促) |
| 0x04 | 補充忘れ | BELL(0004)→0002 | noset | 未セット通知・カード上書き |
| 0x05 | 服薬お知らせ | BELL(0004)→0001 | remind | 記録するが表示しない |
| 0x06 | 補充案内 | BELL(0004)→0002 | refill | 記録し、セット済み判定に使用 |

- 0004(BELL)は「通信できた合図の効果音」。全信号で本編より先に鳴る。
- **noset(補充忘れ)がrefillより後に届いた場合、本日カードのお薬セット状態を「未セット」へ上書きする**(PBX-CAL-260708E以降)。

---

## 5. ダッシュボードの自動更新間隔

| 対象 | 間隔 |
|---|---|
| 記録データ(カレンダー・本日の服薬状況) | **30秒** |
| 服薬時刻の設定 | 10分 |
| 服薬状況(①〜⑤ラベル) | 10分 |

---

## 6. 恒久ルール・命名規則

- **管理番号形式:** `PBX-<領域>-<日付6桁><連番アルファベット>`(例: `PBX-CAL-260708H`)
  領域略称: CAL=index.html / ADM=admin.html / CSS=style.css / ADM-CSS=admin.css / GAS=GAS / RPI=ラズパイ / ESP32=ESP32
- **ZIP作成:** 必ず`rm`で旧ZIP削除→`zip -X -j`で新規作成(上書き禁止)
- **太字:** チャット/Markdown→`**markdown**` / HTMLコード内→`<strong>`(`<b>`禁止)
- **文字幅:** 括弧`()`・スラッシュ`/`・数字は半角。`font-variant-numeric: proportional`
- **機密ルール:** GASコード(`gas0708.txt`)はLINEトークン等を含む可能性があるため非同梱。JuN明示許可時のみ全文出力可
- **CSSキャッシュバスティング:** `style.css`変更時は`index.html`・`admin.html`両方の`?v=`を同時にインクリメント

---

## 7. 未解決・保留事項

| 優先度 | 項目 | 状態 |
|---|---|---|
| 中 | monitor.pyとESP32(new.ino)の0x05/0x06送受信の完全突き合わせ | 未実施 |
| 中 | ラズパイのタイムゾーン(JST)・カメラコマンドの実機確認 | 要実機 |
| 低 | predict.py常駐化の検討 | 保留([MON-091/092]実測待ち) |
| 低 | 管理画面の本格的アクセス制限(Cloudflare Access等) | 未着手 |

---

管理番号: PBX-README-260708A
