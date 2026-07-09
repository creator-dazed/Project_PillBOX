"""
monitor.py — 服薬確認システム（RPi 4用）
=========================================
Python 3.7.3 対応

【配置場所】
  /home/pi/ai101/konoai/monitor.py

【必要ファイル（同じ konoai/ フォルダ内）】
  /home/pi/ai101/konoai/predict.py
  /home/pi/ai101/konoai/transfer.h5
  /home/pi/ai101/konoai/Pictures/image.jpg  ← 自動生成

【前提】
  ケースは1個（仕切りで2区画に分かれている）。
  1回の撮影・1回の predict.py 実行で、
  両区画の状態をまとめて判定したパターンを取得する。

  predict.py の出力は次のような形式：
    "1.1 (99%)"  →  パターン文字列を抽出して利用する

【スプレッドシート連携】
  時刻はハードコードせず、Googleスプレッドシートの
  「setting」シート（2枚目）から読み込む。

  シート: https://**************
  ※シートは「リンクを知っている全員が閲覧可」の共有設定が必要。

  setting シートの構造（行1はヘッダー。行の位置は自由に変えて良い）:
    A列の値が "morning" の行 → B=時 C=分 D=朝
    A列の値が "evening" の行 → B=時 C=分 D=夕
    A列の値が "refill"  の行 → B=時 C=分 D=補充
    ※行番号ではなくA列の名前で該当行を探すため、
      将来シートに行が追加・並び替えされても対応できる。

  B・C列の基準時刻から自動計算:
    朝　: 基準時刻そのもの＝朝の時間告知 / +15分=朝1回目 / +30分=朝2回目
    夕　: 基準時刻そのもの＝夕の時間告知 / +15分=夕1回目 / +30分=夕2回目
    補充: 基準時刻そのもの＝補充の時間告知 / +15分=補充確認1回目 / +30分=補充確認2回目

  取得に失敗した場合は前回値、それも無ければデフォルト値
  （朝8:00・夕19:00・補充20:00）にフォールバックする。

【パターン】
  1.1 → 両方あり（未服用 / 補充済み）
  1.0 → 区画1あり・区画2なし（片方服用済み）
  0.1 → 区画1なし・区画2あり（片方服用済み）
  0.0 → 両方なし（全服用済み）

【実行方法】
  cd /home/pi/ai101/konoai
  python3 monitor.py           # 常駐モード
  python3 monitor.py refill_carryover  # 補充繰越チェック（朝の15分前・繰越し中のみ）
  python3 monitor.py morning0  # 朝の時間告知(0x05)
  python3 monitor.py morning1  # 朝1回目（チェック＋リマインダー）
  python3 monitor.py morning2  # 朝2回目（チェック＋アラート）
  python3 monitor.py night0    # 夕の時間告知
  python3 monitor.py night1    # 夕1回目（チェック＋リマインダー）
  python3 monitor.py night2    # 夕2回目（チェック＋アラート）
  python3 monitor.py refill0   # 補充の時間告知
  python3 monitor.py refill1   # 補充確認1回目（チェック＋補充忘れアラート）
  python3 monitor.py refill2   # 補充確認2回目（チェック＋補充忘れアラート）
  python3 monitor.py demo      # デモモード（シーン選択で確認）

【動作フロー（時刻はスプレッドシートの設定により変動）】
  ※「時間の告知」と「写真判定による確認」を切り離した設計。
    告知(0x05/0x06)はカメラを一切使わず、時刻が来たことだけを送る。

  補充繰越チェック → 朝の15分前。繰越し中の日のみ。0.0なら0x04＋本日終日スキップ [MON-170]
  朝の時間告知 → 写真判定なしでESP32へ告知(0x05・朝夕共通/繰越しスキップ中は送らない)
  朝1回目     → 1.1のときだけ「飲み忘れてませんか」リマインダー(0x03)
                 1.0 か 0.1（片方だけ服用済み）なら → 朝2回目をスキップ
  朝2回目     → 1.1のときだけESP32へアラート(0x01)

  夕の時間告知 → 写真判定なしでESP32へ告知(0x05・朝夕共通)
  夕1回目     → 0.0以外なら「飲み忘れてませんか」リマインダー(0x03)
                 0.0 なら「全服用済み」→ 夕2回目をスキップして終了
  夕2回目     → 0.0以外ならESP32へアラート(0x02)

  補充の時間告知 → 写真判定なしでESP32へ告知(0x06)
  補充確認1回目  → 1.1以外なら「補充されていません」アラート(0x04)
  補充確認2回目  → 1.1以外なら「補充されていません」アラート(0x04)

【補充繰越しロジック（前日の補充確認2回目が0.0だった場合のみ）】 
  前日、補充確認2回目（基準時刻+30分）の結果が完全未補充(0.0)だった場合、
  翌日は次の特別な流れになる（★MON-170で「繰越しチェックを1回に集約」＋
  「スキップ中はお知らせ0x05も鳴らさない(B案)」に変更）:

    補充繰越チェック refill_carryover（朝の基準時刻の15分前）★これ1回だけで判定
      → 撮影・判定して、まだ0.0（完全未補充）なら:
          ・「補充されていません」アラート(0x04)を送信
          ・本日の朝・夕を全てスキップする。具体的には
            朝の時間告知(0x05)/朝1回目/朝2回目/夕の時間告知(0x05)/夕1回目/夕2回目
            を、補充の時間告知(0x06)の時刻まで一切鳴らさない。
      → 0.0でなくなっていれば（＝補充された）繰越し解消。この日は通常運転。

    補充の時間告知 refill0（0x06）
      → ここで繰越しスキップを解除し、通常運転に復帰する。
        以降の補充確認1回目・2回目は毎日いつも通り実行される。
"""

from __future__ import annotations

import csv
import io
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from typing import Optional


# ============================================================
# パス設定（konoai/ 直下に置く前提）
# ============================================================

KONOAI_DIR     = os.path.dirname(os.path.abspath(__file__))
IMAGE_PATH     = os.path.join(KONOAI_DIR, "Pictures", "image.jpg")

#   raspistillは-t未指定だと既定で5000ms(5秒)のプレビュー待機が入り、
#   これが「撮影→ポップアップ表示が遅い」と感じる主因だった。
#   待ち時間を短縮する(値は画質・露出の安定度を見ながら調整すること)。
CAPTURE_WARMUP_MS = 300
CAPTURE_CMD    = "raspistill -o {} -t {}".format(IMAGE_PATH, CAPTURE_WARMUP_MS)
PREDICT_SCRIPT = os.path.join(KONOAI_DIR, "predict.py")
MODEL_PATH     = os.path.join(KONOAI_DIR, "transfer.h5")
LOG_PATH       = os.path.join(KONOAI_DIR, "medication_log.txt")

# アラートコマンド（ESP32へ送る1バイト）
CMD_ALERT_MORNING  = b'\x01'   # 朝の飲み忘れ（2回目 定刻+30分）
CMD_ALERT_NIGHT    = b'\x02'   # 夕の飲み忘れ（2回目 定刻+30分）
CMD_ALERT_REMINDER = b'\x03'   # 飲み忘れてませんか リマインダー（1回目 定刻+15分・朝夕共通）
CMD_ALERT_REFILL   = b'\x04'   # 補充確認1・2回目（定刻+15分/+30分）
CMD_TIME_ANNOUNCE      = b'\x05'   #  朝・夕の定刻告知（写真判定なし・朝夕共通）
CMD_REFILL_ANNOUNCE    = b'\x06'   #  補充の定刻告知（写真判定なし）

#  補充確認の2回目でセット済みが確認できたとき、ラズパイから直接GASへ
# 「refill」を報告するためのURL。ESP32(setting20_1.ino)が使っているものと同じWebアプリ。
GAS_POST_URL = ("https://*********"
                "***********")

# ESP32 シリアル設定
ESP32_PORT     = "/dev/ttyACM0"
ESP32_BAUDRATE = 115200

# パターン文字列の正規表現（"1.1" "0.1" など、小数点付き2桁を抽出）
PATTERN_REGEX = re.compile(r"([01])\.([01])")


# ============================================================
# スプレッドシートからのスケジュール設定読み込み
# ============================================================
# [MON-130] 2026-07-06変更: 行番号ではなくA列の値（名前）で
#   該当行を探す方式にした。以前は「2行目=morning」のように
#   行の位置で決め打ちしていたが、シートに項目が増えて
#   行がずれる（例: evening が4行目、refill が5行目になる等）
#   ことがあっても、A列に "morning"/"evening"/"refill" と
#   書いてありさえすれば正しく読み込めるようにするため。
#
# 例（行の間に他の項目が増えても問題ない）:
#   行1: key      hour  minute  label   ← ヘッダー行
#   行2: morning  8     0       朝
#   行3: (今後使うかもしれない別の項目)
#   行4: evening  19    0       夕
#   行5: refill   20    0       補充
#
# B列=基準時（hour）, C列=基準分（minute）を読み込み、
# そこから +15分 / +30分 したものを実際のチェック時刻とする。
# ============================================================

SPREADSHEET_ID     = "*******"
SETTING_SHEET_GID  = "********"   # 2枚目「setting」シートのgid

# CSVエクスポート用URL（シートが「リンクを知っている全員が閲覧可」である必要あり）
SHEET_CSV_URL = (
    "https://*********"
    .format(SPREADSHEET_ID, SETTING_SHEET_GID)
)

# 対象とするキー（A列の値）と、それぞれで期待するD列ラベル
# 行番号には依存しない。A列の値がこのキーと一致する行を探して使う。
EXPECTED_LABELS_BY_KEY = {
    "morning": "朝",
    "evening": "夕",
    "refill":  "補充",
}
REQUIRED_KEYS = ("morning", "evening", "refill")

# シート取得に失敗した場合のフォールバック値（従来のデフォルト時刻）
DEFAULT_SCHEDULE = {
    "morning": (8, 0),
    "evening": (19, 0),
    "refill":  (20, 0),
}

# キャッシュの再取得間隔（秒）。毎ループごとにシートへアクセスしないための保持。
# ※ここを短くするほどスプレッドシートの変更が早く反映される代わりに
#   Googleサーバーへのアクセス回数が増える。
SCHEDULE_CACHE_SECONDS = 10

# キャッシュ保持用の辞書。中身だけを書き換えるので global 宣言は不要。
_SCHEDULE_STATE = {"data": None, "fetched_at": None}


def fetch_schedule_from_sheet():
    """
    スプレッドシートの setting シートから
    朝／夕／補充 の基準時刻(時,分)を読み込む。 [MON-032]

    [MON-130] 行番号ではなく、A列の値（morning/evening/refill）で
    該当行を探す方式。行の位置がシート側で変わっても対応できる。
    A列がこれら3つのキーに一致しない行（将来追加される項目など）
    は無視する。

    戻り値: {"morning": (h,m), "evening": (h,m), "refill": (h,m)}
            取得や解析に失敗した場合は None を返す。
    """
    # Google側キャッシュを避けるため毎回タイムスタンプを付ける(ダッシュボードと同じ考え方) 
    url = SHEET_CSV_URL + "&_t={}".format(int(time.time()))
    try:
        with urllib.request.urlopen(url, timeout=10) as res:
            raw = res.read().decode("utf-8-sig")
    except Exception as e:
        print("[警告] スプレッドシート取得失敗: {}".format(e))
        return None

    rows = list(csv.reader(io.StringIO(raw)))

    result = {}
    for row in rows[1:]:   # 1行目はヘッダーなのでスキップ 
        if len(row) < 4:
            continue   # 列が足りない行は無視（空行など）

        a_val, b_val, c_val, d_val = [c.strip() for c in row[:4]]
        key = a_val.lower()

        if key not in REQUIRED_KEYS:
            continue   # morning/evening/refill 以外の行は将来の追加項目用として無視 

        expected_label = EXPECTED_LABELS_BY_KEY[key]
        if d_val != expected_label:
            print("[警告] '{}' 行のD列 '{}' が想定 '{}' と異なります".format(
                key, d_val, expected_label))

        try:
            hour   = int(b_val)
            minute = int(c_val)
        except ValueError:
            print("[警告] '{}' 行の時刻を数値として読み取れません: B={!r} C={!r}".format(
                key, b_val, c_val))
            return None

        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            print("[警告] '{}' 行の時刻が範囲外です: {}:{}".format(key, hour, minute))
            return None

        result[key] = (hour, minute)

    missing = [k for k in REQUIRED_KEYS if k not in result]
    if missing:
        print("[警告] シートに必要な行が見つかりません: {}".format(missing))
        return None

    return result


def get_schedule():
    """
    キャッシュを確認し、必要なら再取得しつつスケジュールを返す。 [MON-034]
    取得に失敗した場合は直前の値、それも無ければデフォルト値を使う
    （インターネット障害時もシステムを止めないためのフェイルセーフ）。
    """
    now         = datetime.now()
    cached      = _SCHEDULE_STATE["data"]
    fetched_at  = _SCHEDULE_STATE["fetched_at"]

    need_refresh = (
        cached is None or fetched_at is None or
        (now - fetched_at).total_seconds() >= SCHEDULE_CACHE_SECONDS
    )

    if need_refresh:
        fetched = fetch_schedule_from_sheet()
        if fetched is not None:
            _SCHEDULE_STATE["data"]       = fetched
            _SCHEDULE_STATE["fetched_at"] = now
            print("[設定] スプレッドシートから時刻を読み込みました: {}".format(fetched))
        elif cached is None:
            print("[設定] シート取得失敗のためデフォルト値を使用します: {}".format(DEFAULT_SCHEDULE))
            _SCHEDULE_STATE["data"]       = dict(DEFAULT_SCHEDULE)
            _SCHEDULE_STATE["fetched_at"] = now
        else:
            print("[設定] シート取得失敗のため前回値を継続使用します: {}".format(cached))

    return _SCHEDULE_STATE["data"]


def _add_minutes(hour, minute, add):
    """時・分に分数を加算し、繰り上がりを考慮した(時,分)を返す。 [MON-035]"""
    total = (hour * 60 + minute + add) % (24 * 60)
    return (total // 60, total % 60)


def compute_check_times():
    """
    スプレッドシートの基準時刻から実際のチェック時刻を計算する。 [MON-036]
    朝・夕（夕）・補充のいずれも基準時刻の+15分／+30分の2回。 [MON-140]

    "morning0"/"night0"/"refill0" は基準時刻そのもの（オフセットなし）。 [MON-160]
    朝・夕の定刻告知(0x05)、補充の定刻告知(0x06)、
    および前日の補充確認2回目が0.0だった場合の朝の特別チェックに使う。 [MON-150]

    戻り値の例:
      {"refill_carryover": (7,45),
       "morning0": (8,0),
       "morning1": (8,15), "morning2": (8,30),
       "night0": (19,0),
       "night1": (19,15),  "night2": (19,30),
       "refill0": (20,0),
       "refill1": (20,15), "refill2": (20,30)}
    """
    sched = get_schedule()
    m_h, m_m = sched["morning"]
    e_h, e_m = sched["evening"]
    r_h, r_m = sched["refill"]

    return {
        #  繰越しチェック専用の時刻。朝の基準時刻の15分前。
        #   前日の補充確認2回目が0.0だった日だけ使う。マイナス加算でも
        #   _add_minutes が日跨ぎ(例:0:00の15分前=前日23:45)を正しく計算する。
        "refill_carryover": _add_minutes(m_h, m_m, -15),
        "morning0": (m_h, m_m),
        "morning1": _add_minutes(m_h, m_m, 15),
        "morning2": _add_minutes(m_h, m_m, 30),
        "night0":   (e_h, e_m),
        "night1":   _add_minutes(e_h, e_m, 15),
        "night2":   _add_minutes(e_h, e_m, 30),
        "refill0":  (r_h, r_m),
        "refill1":  _add_minutes(r_h, r_m, 15),
        "refill2":  _add_minutes(r_h, r_m, 30),
    }


# ============================================================
# 起動時パス表示
# ============================================================

def show_paths():
    print("=" * 50)
    print("服薬確認システム 起動")
    print("=" * 50)
    print("  konoai ディレクトリ: {}".format(KONOAI_DIR))
    print("  推論スクリプト     : {}".format(PREDICT_SCRIPT))
    print("  モデル             : {}".format(MODEL_PATH))
    print("  撮影先             : {}".format(IMAGE_PATH))
    print("  撮影の待機時間     : {}ms".format(CAPTURE_WARMUP_MS))
    print("  ログ               : {}".format(LOG_PATH))
    print("  ESP32ポート        : {}".format(ESP32_PORT))
    print("  設定シート         : {}".format(SHEET_CSV_URL))
    print("")

    times = compute_check_times()
    mb_h, mb_m = times["morning0"]
    mh1, mm1 = times["morning1"]
    mh2, mm2 = times["morning2"]
    nb_h, nb_m = times["night0"]
    nh1, nm1 = times["night1"]
    nh2, nm2 = times["night2"]
    rb_h, rb_m = times["refill0"]
    rh1, rm1 = times["refill1"]
    rh2, rm2 = times["refill2"]

    print("  チェック時刻（スプレッドシートより算出）:")
    print("    {:02d}:{:02d}  → 朝の時間告知（0x05・写真判定なし）＋補充繰越チェック".format(mb_h, mb_m))
    print("    {:02d}:{:02d}  → 朝1回目（チェック＋リマインダー 0x03 / 1.1のみ）".format(mh1, mm1))
    print("    {:02d}:{:02d}  → 朝2回目（チェック＋アラート 0x01 / 1.1のみ）".format(mh2, mm2))
    print("    {:02d}:{:02d} → 夕の時間告知（0x05・写真判定なし）".format(nb_h, nb_m))
    print("    {:02d}:{:02d} → 夕1回目（チェック＋リマインダー 0x03 / 0.0なら終了）".format(nh1, nm1))
    print("    {:02d}:{:02d} → 夕2回目（チェック＋アラート 0x02）".format(nh2, nm2))
    print("    {:02d}:{:02d} → 補充の時間告知（0x06・写真判定なし）".format(rb_h, rb_m))
    print("    {:02d}:{:02d} → 補充確認1回目（1.1以外なら補充忘れアラート 0x04）".format(rh1, rm1))
    print("    {:02d}:{:02d} → 補充確認2回目（1.1以外なら補充忘れアラート 0x04）".format(rh2, rm2))
    print("=" * 50)


# ============================================================
# ファイル存在確認
# ============================================================

def check_files():
    ok = True
    for path in [PREDICT_SCRIPT, MODEL_PATH]:
        if os.path.exists(path):
            print("  [OK] {}".format(path))
        else:
            print("  [NG] 見つかりません: {}".format(path))
            ok = False
    return ok


# ============================================================
# カメラ撮影
# ============================================================

def capture_image():
    os.makedirs(os.path.dirname(IMAGE_PATH), exist_ok=True)

    # [MON-091] 「音が鳴るまで遅い」原因の切り分け用に、撮影だけにかかった時間を計測する。
    t_before = time.time()
    result = subprocess.run(
        CAPTURE_CMD.split(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    elapsed = time.time() - t_before

    if result.returncode != 0:
        print("[エラー] 撮影失敗: {}".format(result.stderr.decode()))
        return False
    print("[撮影] {} 保存完了（所要時間: {:.1f}秒）".format(IMAGE_PATH, elapsed))
    return True


# ============================================================
# 推論（predict.py を1回呼び出し、パターンを取得する）
# ============================================================

def predict_pattern(image_path):
    """
    predict.py を実行し、出力から "1.1" のようなパターン文字列を抽出する。
    戻り値: "1.1" / "1.0" / "0.1" / "0.0" / None（エラー・解析失敗）
    """
    cmd = ["python3", PREDICT_SCRIPT, image_path]

    # [MON-092] predict.pyは呼び出すたびに新しいプロセスとして起動しており、
    #   AIライブラリとモデルの読み込みがそのたびに発生する。
    #   「音が鳴るまで遅い」原因の切り分け用に、ここにかかった時間を計測する。
    t_before = time.time()
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=KONOAI_DIR,
    )
    elapsed = time.time() - t_before

    if result.returncode != 0:
        print("[エラー] 推論失敗: {}".format(result.stderr.decode()))
        return None

    output = result.stdout.decode().strip()
    print("[推論出力] {}（所要時間: {:.1f}秒）".format(output, elapsed))

    match = PATTERN_REGEX.search(output)
    if not match:
        print("[警告] predict.py の出力からパターンを抽出できません: {!r}".format(output))
        return None

    return "{}.{}".format(match.group(1), match.group(2))


def _print_pattern_meaning(pattern):
    meanings = {
        "1.1": "両方あり（未服用 / 補充済み）",
        "1.0": "区画1あり・区画2なし",
        "0.1": "区画1なし・区画2あり",
        "0.0": "両方なし（全服用済み）",
    }
    print("  意味: {}".format(meanings.get(pattern, "不明")))


# ============================================================
# ESP32 アラート送信（接続を1回だけ開き、使い回す方式）
#   ・従来は送信のたびにポートを開閉していたため、ESP32-C3が
#     そのたびに再起動し、音が鳴るまで時間がかかっていた。
#   ・接続をプログラム開始時に1回だけ開き、以降は同じ接続で
#     送信することで再起動を防ぐ。
# ============================================================

def open_esp32_serial():
    """
    ESP32との接続を1回だけ開く。プログラム開始時に呼ぶ。 // MON-061
    開くのに失敗しても None を返すだけで、システムは止めない。
    戻り値: serial.Serial のインスタンス / None
    """
    try:
        import serial
    except ImportError:
        print("[警告] pyserial 未インストール。以降はDRY-RUN（送信せず表示のみ）で動作します。")
        return None

    try:
        ser = serial.Serial(ESP32_PORT, ESP32_BAUDRATE, timeout=2)
        # 接続を開いた直後はESP32が再起動することがあるため、
        # 準備が整うまで少し待ってから使い始める。 
        time.sleep(2)
        print("[ESP32] 接続を開きました（この接続を使い回します）: {}".format(ESP32_PORT))
        return ser
    except Exception as e:
        print("[エラー] ESP32接続を開けません: {}（以降はDRY-RUN）".format(e))
        return None


def close_esp32_serial(ser):
    """開いてあるESP32接続を閉じる。プログラム終了時に呼ぶ。 // MON-064"""
    if ser is None:
        return
    try:
        ser.close()
        print("[ESP32] 接続を閉じました。")
    except Exception as e:
        print("[警告] ESP32接続のクローズに失敗: {}".format(e))


def send_alert_to_esp32(ser, cmd_byte, session):
    """
    すでに開いてある接続(ser)を使ってアラート1バイトを送る。 // MON-063
    ser が None（接続に失敗している）場合は、送信せず表示だけ行う。

    [MON-080] 原因切り分け用の診断ログ:
      送信直前・直後の時刻をミリ秒まで記録して表示する。
      ここが一瞬（数ms程度）で終わっていれば、
      2〜5分の遅延はPython/ラズパイ側ではなく
      ESP32側（配線・ファームウェア）で起きていると判断できる。
    """
    if ser is None:
        print("  [DRY-RUN] {} アラート: 0x{}".format(session, cmd_byte.hex()))
        return False

    try:
        t_before = datetime.now()
        ser.write(cmd_byte)
        ser.flush()   
        t_after = datetime.now()

        elapsed_ms = (t_after - t_before).total_seconds() * 1000
        print("[ESP32] {} アラート送信 → スピーカー鳴動".format(session))
        print("  [診断] Python側の送信処理時間: {:.1f}ms （{} → {}）".format(
            elapsed_ms,
            t_before.strftime("%H:%M:%S.%f")[:-3],
            t_after.strftime("%H:%M:%S.%f")[:-3],
        ))
        print("  [診断] ↑この時刻とスピーカーが実際に鳴った時刻を見比べてください。")
        return True
    except Exception as e:
        print("[エラー] ESP32送信失敗: {}".format(e))
        return False


def post_event_to_gas(event, detail):
    """
    [MON-193] GASへイベントを1件報告する（補充セット済みの記録用）。
    ESP32を経由しない(=音は鳴らさない)、記録専用の静かな報告。
    失敗しても監視本体を止めないよう、例外はすべて握って警告表示のみ行う。
    GASは302リダイレクトを返すが、記録はリダイレクト前に完了しているため
    応答内容は確認しない（ESP32側と同じ扱い）。
    """
    import json
    try:
        payload = json.dumps({"event": event, "detail": detail}).encode("utf-8")
        req = urllib.request.Request(
            GAS_POST_URL, data=payload,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10):
            pass
        print("  [GAS] 報告送信: {} ({})".format(event, detail))
        return True
    except Exception as e:
        print("  [警告] GAS報告失敗({}): {}".format(event, e))
        return False


# ============================================================
# 1回の撮影・判定（撮影 → predict.py 実行 → パターン取得）
# ============================================================

def run_capture_and_predict():
    """
    1回撮影して predict.py を実行し、パターン文字列を返す。
    戻り値: "1.1" 等 / None（エラー時）
    """
    if not capture_image():
        return None
    return predict_pattern(IMAGE_PATH)


# ============================================================
# チェックのみ（アラートなし）
# ============================================================

def check_only(session):
    """
    撮影・判定のみ行い、アラートは送らない。
    戻り値: パターン文字列 / None（エラー）
    """
    print("\n" + "=" * 50)
    print("【{}チェック】 {}".format(
        session, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    print("=" * 50)

    pattern = run_capture_and_predict()
    if pattern is None:
        print("[エラー] 判定に失敗しました。")
        log_event(session, "ERROR", "判定失敗")
        return None

    print("\n  パターン: {}".format(pattern))
    _print_pattern_meaning(pattern)
    log_event(session, pattern, "チェックのみ")
    return pattern


# ============================================================
# チェック＋アラート送信（0.0以外でアラート）
# ============================================================

def check_and_alert(ser, session, alert_cmd):
    """
    撮影・判定を行い、0.0以外ならアラートを送信する。 // MON-065
    ser: 開いてあるESP32接続（send_alert_to_esp32へ渡す）
    戻り値: パターン文字列 / None（エラー）
    """
    print("\n" + "=" * 50)
    print("【{}チェック＋アラート】 {}".format(
        session, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    print("=" * 50)

    if not capture_image():
        print("[エラー] 撮影に失敗しました。")
        log_event(session, "ERROR", "撮影失敗")
        return None

    show_image_popup(IMAGE_PATH)  

    pattern = predict_pattern(IMAGE_PATH)
    if pattern is None:
        print("[エラー] 判定に失敗しました。")
        log_event(session, "ERROR", "判定失敗")
        return None

    print("\n  パターン: {}".format(pattern))
    _print_pattern_meaning(pattern)

    if pattern == "0.0":
        print("\n  → 全服用済み。アラートなし。")
        log_event(session, pattern, "服用済み")
    else:
        print("\n  → 薬が残っています。ESP32へアラート送信します。")
        send_alert_to_esp32(ser, alert_cmd, session)
        log_event(session, pattern, "アラート送信")

    return pattern


# ============================================================
# 朝専用チェック＋アラート送信（1.1のときのみアラート）
# ============================================================

def check_and_alert_if_full(ser, session, alert_cmd):
    """
    朝のチェック専用。撮影・判定を行い、 // MON-066
    パターンが 1.1（両方まだ服用されていない）のときのみアラートを送信する。
    1.0 / 0.1（片方服用済み）/ 0.0（両方服用済み）ではアラートを送らない。
    ser: 開いてあるESP32接続（send_alert_to_esp32へ渡す）
    """
    print("\n" + "=" * 50)
    print("【{}チェック＋アラート】 {}".format(
        session, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    print("=" * 50)

    if not capture_image():
        print("[エラー] 撮影に失敗しました。")
        log_event(session, "ERROR", "撮影失敗")
        return None

    show_image_popup(IMAGE_PATH)   

    pattern = predict_pattern(IMAGE_PATH)
    if pattern is None:
        print("[エラー] 判定に失敗しました。")
        log_event(session, "ERROR", "判定失敗")
        return None

    print("\n  パターン: {}".format(pattern))
    _print_pattern_meaning(pattern)

    if pattern == "1.1":
        print("\n  → 両方とも未服用です。ESP32へアラート送信します。")
        send_alert_to_esp32(ser, alert_cmd, session)
        log_event(session, pattern, "アラート送信")
    else:
        print("\n  → いずれか服用済みのためアラートなし。")
        log_event(session, pattern, "アラートなし")

    return pattern


# ============================================================
# 補充確認（1.1以外なら補充忘れアラート）
# ============================================================

def check_refill(ser, session, alert_cmd):
    """
    補充確認。撮影・判定を行い、 // MON-067
    パターンが 1.1（両方補充済み）でなければアラートを送信する。
    ser: 開いてあるESP32接続（send_alert_to_esp32へ渡す）

    [MON-140] 補充確認1回目・2回目のどちらからも同じこの関数を呼ぶ。
              session名（"補充確認1回目"/"補充確認2回目"）で区別する。
    """
    print("\n" + "=" * 50)
    print("【{}】 {}".format(
        session, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    print("=" * 50)

    if not capture_image():
        print("[エラー] 撮影に失敗しました。")
        log_event(session, "ERROR", "撮影失敗")
        return None

    show_image_popup(IMAGE_PATH)  

    pattern = predict_pattern(IMAGE_PATH)
    if pattern is None:
        print("[エラー] 判定に失敗しました。")
        log_event(session, "ERROR", "判定失敗")
        return None

    print("\n  パターン: {}".format(pattern))
    _print_pattern_meaning(pattern)

    if pattern == "1.1":
        print("\n  → 両方補充済みです。アラートなし。")
        post_event_to_gas("refill", "camera")  
        log_event(session, pattern, "補充済み・GAS報告")
    else:
        print("\n  → 補充されていません。ESP32へアラート送信します。")
        send_alert_to_esp32(ser, alert_cmd, session)
        log_event(session, pattern, "補充忘れアラート送信")

    return pattern


# ============================================================
# 補充繰越しチェック（前日の補充確認2回目が0.0だった場合の翌朝処理）
# ============================================================

def check_refill_carryover(ser, session):
    """
    [MON-150] 前日の「補充確認2回目」が0.0（完全に未補充）だった場合のみ
    翌朝に実行される特別チェック。

    通常の check_refill とはアラート条件が異なる点に注意:
      通常の check_refill  → 「1.1以外」でアラート（部分的な不足も対象）
      この関数              → 「0.0のときだけ」アラート（完全に空の場合のみ）

    ser: 開いてあるESP32接続（send_alert_to_esp32へ渡す）
    戻り値: パターン文字列 / None（エラー時）
    """
    print("\n" + "=" * 50)
    print("【{}】 {}".format(
        session, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    print("=" * 50)

    if not capture_image():
        print("[エラー] 撮影に失敗しました。")
        log_event(session, "ERROR", "撮影失敗")
        return None

    show_image_popup(IMAGE_PATH)   

    pattern = predict_pattern(IMAGE_PATH)
    if pattern is None:
        print("[エラー] 判定に失敗しました。")
        log_event(session, "ERROR", "判定失敗")
        return None

    print("\n  パターン: {}".format(pattern))
    _print_pattern_meaning(pattern)

    if pattern == "0.0":
        print("\n  → まだ補充されていません。ESP32へアラート送信します。")
        send_alert_to_esp32(ser, CMD_ALERT_REFILL, session)
        log_event(session, pattern, "補充忘れアラート再送信")
    else:
        print("\n  → 補充が確認できました。")
        log_event(session, pattern, "補充確認・繰越し解消")

    return pattern


# ============================================================
# 定刻の告知（写真判定なし）
#   「時間を切り離す」ため、カメラ撮影・AI判定を一切行わず、
#   時刻になったことだけをESP32へ知らせる。
# ============================================================

def announce_time(ser, session, alert_cmd):
    """
    時刻が来たことをESP32へ知らせるだけの、写真判定を伴わない告知。 [MON-160]
    - 朝・夕の定刻告知: CMD_TIME_ANNOUNCE (0x05) 朝夕共通
    - 補充の定刻告知  : CMD_REFILL_ANNOUNCE (0x06)

    ser: 開いてあるESP32接続（send_alert_to_esp32へ渡す）
    """
    print("\n" + "=" * 50)
    print("【{}】 {}".format(
        session, datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    print("=" * 50)
    print("  → 時刻になりました。ESP32へ告知を送信します（写真判定なし）。")
    send_alert_to_esp32(ser, alert_cmd, session)
    log_event(session, "-", "定刻告知送信")


# ============================================================
# デモモード（ストーリー形式・複数チェックポイント対応） 
# ============================================================

# ============================================================
# 撮影した画像のポップアップ表示 
#   デモ実行（_demo_capture_and_show経由）に加え、
#   本番の自動チェック（check_and_alert等）でも撮影直後に画面表示する。
#   非同期(Popen)・失敗しても本体を止めない作りのため、
#   本番のメインループ(分単位の時刻一致判定)を遅らせる心配はない。
# ============================================================

DEMO_IMAGE_DISPLAY_SECONDS = 4   # ポップアップを自動で閉じるまでの秒数

# 順番に探して最初に見つかったものを使う（環境によって入っているものが違うため）
IMAGE_VIEWER_CANDIDATES = ["feh", "gpicview", "eog", "xdg-open"]


def show_image_popup(image_path):
    """
    撮影した画像をポップアップ表示する。 [MON-103][MON-190]
    デモ・本番どちらの実行からも呼ばれる共通処理。
    - よく使われる画像ビューアを順番に探し、見つかったものを使う。
    - 進行を止めないよう、表示は非同期（プログラムを待たせない）で行う。
    - timeoutコマンドが使える場合、一定秒数で自動的にウィンドウを閉じる。
    - 表示に失敗しても本体は止めず、警告を出すだけにする。
    """
    import shutil

    viewer = None
    for candidate in IMAGE_VIEWER_CANDIDATES:
        if shutil.which(candidate):
            viewer = candidate
            break

    if viewer is None:
        print("[警告] 画像を表示するビューアが見つかりませんでした。")
        print("  例: sudo apt install feh  でインストールできます。")
        return

    try:
        if shutil.which("timeout"):
            cmd = ["timeout", str(DEMO_IMAGE_DISPLAY_SECONDS), viewer, image_path]
        else:
            cmd = [viewer, image_path]

        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[デモ] 撮影した画像を表示しています（{}、約{}秒間）".format(
            viewer, DEMO_IMAGE_DISPLAY_SECONDS))
    except Exception as e:
        print("[警告] 画像のポップアップ表示に失敗しました: {}".format(e))
        print("  （表示できなくてもデモ自体は続行します）")


def _demo_capture_and_show(step_title):
    """
    デモの共通処理：撮影→ポップアップ表示→判定→パターン表示を行う。
    各シーン（15分／30分／補充確認）から呼び出して使う。

    戻り値: パターン文字列（例:"1.1"）/ None（撮影・推論失敗時）
    """
    print("")
    print("-" * 50)
    print("【{}】".format(step_title))
    print("-" * 50)
    input("  ケースをカメラの前に置いてからEnterを押してください...")

    if not capture_image():
        print("[デモ中断] 撮影に失敗しました。")
        return None

    # 撮影直後に画像をポップアップ表示する（デモ専用機能） [MON-104]
    show_image_popup(IMAGE_PATH)

    pattern = predict_pattern(IMAGE_PATH)
    if pattern is None:
        print("[デモ中断] 推論に失敗しました。")
        return None

    print("")
    print("  判定パターン: {}".format(pattern))
    _print_pattern_meaning(pattern)
    return pattern


def demo_check_reminder(ser):
    """
    シーン1: 中間15分チェック（8:15 / 19:15 相当）。
    「飲み忘れていませんか？」のリマインダー(0x03)を
    送るかどうかをその場で選べる。
    ser: 開いてあるESP32接続（send_alert_to_esp32へ渡す）

    本番ルールは朝と夕で条件が違うため、
    参考として両方の判定結果を表示してから選択させる。
    """
    pattern = _demo_capture_and_show("15分チェック（中間確認）")
    if pattern is None:
        return

    would_alert_morning = (pattern == "1.1")    
    would_alert_night   = (pattern != "0.0")    

    print("")
    print("  [参考] 本番ルールではこう判定されます")
    print("    朝のルール（1.1のときだけ送信） : {}".format(
        "送信する" if would_alert_morning else "送信しない"))
    print("    夕のルール（0.0以外は送信）     : {}".format(
        "送信する" if would_alert_night else "送信しない"))

    ans = input("\n  → 飲み忘れリマインダー(0x03)をESP32へ送信しますか？ [y/N]: ")
    if ans.strip().lower() == "y":
        send_alert_to_esp32(ser, CMD_ALERT_REMINDER, "15分チェック(デモ)")
        log_event("デモ15分", pattern, "リマインダー送信")
    else:
        print("  → 送信をスキップしました。")
        log_event("デモ15分", pattern, "送信スキップ")


def demo_check_alert(ser):
    """
    シーン2: 30分チェック（8:30 / 19:30 相当）。 [MON-013] // MON-069
    朝(0x01) / 夕(0x02) を選んで送信できる。
    ser: 開いてあるESP32接続（send_alert_to_esp32へ渡す）

    [MON-110] シーン1・3と統一するため、0.0（服用済み）でも
    「それでもテスト送信しますか？」と聞けるようにした。
    """
    pattern = _demo_capture_and_show("30分チェック（飲み忘れアラート）")
    if pattern is None:
        return

    print("")
    if pattern == "0.0":
        print("  → 両方服用済みです。本来はアラート不要です。")
        ans = input("  それでもテスト送信してみますか？ [y/N]: ")
    else:
        ans = input("  → 薬が残っています。ESP32へアラートを送信しますか？ [y/N]: ")

    if ans.strip().lower() == "y":
        session = input("  朝(m) / 夕(n) どちらのアラートを送りますか？ [m/n]: ").strip().lower()
        if session == "n":
            send_alert_to_esp32(ser, CMD_ALERT_NIGHT, "夕2回目(デモ)")
            log_event("デモ30分", pattern, "夕アラート送信")
        else:
            send_alert_to_esp32(ser, CMD_ALERT_MORNING, "朝2回目(デモ)")
            log_event("デモ30分", pattern, "朝アラート送信")
    else:
        print("  → アラート送信をスキップしました。")
        log_event("デモ30分", pattern, "送信スキップ")


def demo_check_refill(ser):
    """
    シーン3: 20:15 翌日分補充チェック。 [MON-014] // MON-070
    パターンが 1.1（両方補充済み）以外なら
    補充忘れアラート(0x04)を送るかどうかを選べる。
    ser: 開いてあるESP32接続（send_alert_to_esp32へ渡す）
    """
    pattern = _demo_capture_and_show("20:15チェック（翌日分補充確認）")
    if pattern is None:
        return

    print("")
    if pattern == "1.1":
        print("  → 両方とも補充済みです。本来はアラート不要です。")
        post_event_to_gas("refill", "camera")  
        ans = input("  それでもテスト送信してみますか？ [y/N]: ")
    else:
        print("  → 補充が不足しています。")
        ans = input("  → 補充忘れアラート(0x04)をESP32へ送信しますか？ [y/N]: ")

    if ans.strip().lower() == "y":
        send_alert_to_esp32(ser, CMD_ALERT_REFILL, "補充確認(デモ)")
        log_event("デモ補充", pattern, "補充忘れアラート送信")
    else:
        print("  → 送信をスキップしました。")
        log_event("デモ補充", pattern, "送信スキップ")


def demo_full_story(ser):
    """
    通しストーリー: 15分→30分→補充確認 を順番に実施する。
    発表・デモンストレーション用に、ケースの状態を
    途中で変えながら一連の流れとして見せられるようにする。
    ser: 開いてあるESP32接続（各デモ関数へ渡す）
    """
    print("")
    print("=" * 50)
    print("【通しストーリーデモ】1日の流れを再現します")
    print("=" * 50)

    print("\n[シーン 1/3] まずは中間15分チェックです。")
    demo_check_reminder(ser)

    print("\n[シーン 2/3] 続いて30分チェックです。")
    demo_check_alert(ser)

    print("\n[シーン 3/3] 最後に翌日分の補充確認です。")
    demo_check_refill(ser)

    print("\n【通しストーリーデモ 終了】")


def run_demo(ser):
    """
    デモ用メインメニュー。
    python3 monitor.py demo  で実行。
    シーンを個別に試すことも、通しストーリーで
    一気に流すこともできる。
    ser: 開いてあるESP32接続（各デモ関数へ渡す）
    """
    print("")
    print("=" * 50)
    print("【デモモード】")
    print("  モデル    : {}".format(MODEL_PATH))
    print("  ESP32ポート: {}".format(ESP32_PORT))
    print("=" * 50)

    while True:
        print("")
        print("  どのシーンを実行しますか？")
        print("    1 = 15分チェック（リマインダー 0x03）")
        print("    2 = 30分チェック（アラート 0x01/0x02）")
        print("    3 = 20:15補充チェック（補充忘れ 0x04）")
        print("    4 = 通しストーリー（1→2→3を順番に実施）")
        print("    q = デモ終了")
        choice = input("  選択 [1/2/3/4/q]: ").strip().lower()

        if choice == "1":
            demo_check_reminder(ser)
        elif choice == "2":
            demo_check_alert(ser)
        elif choice == "3":
            demo_check_refill(ser)
        elif choice == "4":
            demo_full_story(ser)
        elif choice == "q":
            print("  デモを終了します。")
            break
        else:
            print("  [警告] 1 / 2 / 3 / 4 / q のいずれかを入力してください。")


# ============================================================
# ログ
# ============================================================

def log_event(session, pattern, note=""):
    now     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = "[{}] {} パターン={} {}".format(now, session, pattern, note)
    print("[LOG] {}".format(message))
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(message + "\n")


# ============================================================
# エントリポイント
# ============================================================

def main():
    show_paths()

    print("\nファイル確認中...")
    if not check_files():
        print("\n[エラー] 必要なファイルが見つかりません。")
        sys.exit(1)

    if len(sys.argv) > 1:
        arg = sys.argv[1]

        # 「使い方」を表示するだけのときはESP32接続を開かない（無駄なリセットを避ける）//
        known_args = ("refill_carryover",
                      "morning0", "morning1", "morning2", "night0", "night1", "night2",
                      "refill0", "refill1", "refill2", "demo")
        if arg not in known_args:
            times = compute_check_times()
            print("使い方: python3 monitor.py [refill_carryover|morning0|morning1|morning2|night0|night1|night2|refill0|refill1|refill2|demo]")
            print("  refill_carryover = 補充繰越チェック（{:02d}:{:02d} 朝の15分前・繰越し中の日のみ本番実行）".format(*times["refill_carryover"]))
            print("  morning0 = 朝の時間告知(0x05)（{:02d}:{:02d}）".format(*times["morning0"]))
            print("  morning1 = 朝1回目（{:02d}:{:02d} チェック＋リマインダー / 1.1のみ）".format(*times["morning1"]))
            print("  morning2 = 朝2回目（{:02d}:{:02d} チェック＋アラート / 1.1のみ）".format(*times["morning2"]))
            print("  night0   = 夕の時間告知(0x05)（{:02d}:{:02d}）".format(*times["night0"]))
            print("  night1   = 夕1回目（{:02d}:{:02d} チェック＋リマインダー）".format(*times["night1"]))
            print("  night2   = 夕2回目（{:02d}:{:02d} チェック＋アラート）".format(*times["night2"]))
            print("  refill0  = 補充の時間告知(0x06)（{:02d}:{:02d}）".format(*times["refill0"]))
            print("  refill1  = 補充確認1回目（{:02d}:{:02d} チェック＋補充忘れアラート）".format(*times["refill1"]))
            print("  refill2  = 補充確認2回目（{:02d}:{:02d} チェック＋補充忘れアラート）".format(*times["refill2"]))
            print("  demo     = デモモード（15分/30分/補充チェックをシーン選択で確認）")
            return

        # ここから先はESP32へ送信する可能性があるので、接続を1回だけ開く //
        ser = open_esp32_serial()
        try:
            if arg == "morning0":
                announce_time(ser, "朝の時間告知", CMD_TIME_ANNOUNCE)
            elif arg == "refill_carryover":
                check_refill_carryover(ser, "補充繰越チェック")  
            elif arg == "morning1":
                check_and_alert_if_full(ser, "朝1回目", CMD_ALERT_REMINDER)
            elif arg == "morning2":
                check_and_alert_if_full(ser, "朝2回目", CMD_ALERT_MORNING)
            elif arg == "night0":
                announce_time(ser, "夕の時間告知", CMD_TIME_ANNOUNCE)
            elif arg == "night1":
                check_and_alert(ser, "夕1回目", CMD_ALERT_REMINDER)
            elif arg == "night2":
                check_and_alert(ser, "夕2回目", CMD_ALERT_NIGHT)
            elif arg == "refill0":
                announce_time(ser, "補充の時間告知", CMD_REFILL_ANNOUNCE)
            elif arg == "refill1":
                check_refill(ser, "補充確認1回目", CMD_ALERT_REFILL)
            elif arg == "refill2":
                check_refill(ser, "補充確認2回目", CMD_ALERT_REFILL)
            elif arg == "demo":
                run_demo(ser)
        finally:
            close_esp32_serial(ser)   # 何があっても接続を閉じる
        return

    # 常駐モード
    print("\n[常駐モード] Ctrl+C で終了\n")

    # ESP32接続を1回だけ開き、ループ全体で使い回す（送信のたびの再起動を防ぐ）
    ser = open_esp32_serial()

    last_run        = {}   # (date, hour, minute) → True
    morning0_pattern = {}   # date → 朝の補充繰越チェックのパターン 
    morning1_pattern = {}   # date → 朝1回目のパターン 
    night1_pattern  = {}   # date → 夕1回目のパターン
    skip_today      = {}   # date → True ならその日の朝2/夕1/夕2をスキップ 

    # 前日の補充確認2回目の結果。日付をまたいでも保持する
    # （日付変更のクリーンアップ対象には含めない）。
    last_refill2_pattern = None
    last_refill2_date    = None

    # Ctrl+Cで止めても必ず接続を閉じられるよう try/finally で囲む 
    try:
        while True:
            now  = datetime.now()
            date = now.date()
            h    = now.hour
            m    = now.minute

            # 日付が変わったら前日までのトリガー履歴を掃除（長期常駐でのメモリ肥大防止）[MON-052]
            last_run        = {k: v for k, v in last_run.items() if k[0] == date}
            morning0_pattern = {k: v for k, v in morning0_pattern.items() if k == date}
            morning1_pattern = {k: v for k, v in morning1_pattern.items() if k == date}
            night1_pattern  = {k: v for k, v in night1_pattern.items() if k == date}
            skip_today      = {k: v for k, v in skip_today.items() if k == date}

            times = compute_check_times()
            rc_h, rc_m = times["refill_carryover"]   # 朝の15分前
            mb_h, mb_m = times["morning0"]
            mh1, mm1 = times["morning1"]
            mh2, mm2 = times["morning2"]
            nb_h, nb_m = times["night0"]
            nh1, nm1 = times["night1"]
            nh2, nm2 = times["night2"]
            rb_h, rb_m = times["refill0"]
            rh1, rm1 = times["refill1"]
            rh2, rm2 = times["refill2"]

            #前日の補充確認2回目が0.0（完全未補充）だったかどうか
            yesterday = date - timedelta(days=1)
            carryover_today = (
                last_refill2_pattern == "0.0" and last_refill2_date == yesterday
            )

            # 補充繰越チェック（朝の基準時刻の15分前・繰越し中の日だけ）
            #   ここで撮影・判定し、まだ0.0（完全未補充）なら:
            #     ・0x04(補充忘れ)を送る（check_refill_carryover内）
            #     ・skip_today を立て、本日の朝(お知らせ0x05含む)〜夕を全てスキップ(B案)
            #   0.0でなくなっていれば繰越し解消、この日は通常運転に戻る。
            key = (date, rc_h, rc_m)
            if carryover_today and h == rc_h and m == rc_m and key not in last_run:
                pattern = check_refill_carryover(ser, "補充繰越チェック")
                morning0_pattern[date] = pattern
                if pattern == "0.0":
                    skip_today[date] = True
                    print("\n  → 補充が確認できないため、本日の朝・夕のお知らせと"
                          "チェックは、補充のお知らせ時刻まで全てスキップします。")
                    log_event("補充繰越チェック", pattern, "補充繰越によりスキップ設定(朝夕告知含む)")
                last_run[key] = True

            # 朝の定刻: 時間告知(0x05) 
            #   ★B案: 補充繰越スキップ中は、お知らせ(0x05)も鳴らさない。
            key = (date, mb_h, mb_m)
            if h == mb_h and m == mb_m and key not in last_run:
                if skip_today.get(date):
                    print("\n[{:02d}:{:02d}] 補充繰越のためスキップ中（お知らせも送信しません）".format(mb_h, mb_m))
                    log_event("朝の時間告知", "SKIP", "補充繰越によるスキップ中")
                else:
                    announce_time(ser, "朝の時間告知", CMD_TIME_ANNOUNCE)
                last_run[key] = True

            # 朝1回目 チェック＋リマインダー（1.1のときのみ送信）
            # 繰越しチェックは refill_carryover に一本化したため、
            #           ここでは通常のチェックのみ。スキップ中なら何もしない。
            key = (date, mh1, mm1)
            if h == mh1 and m == mm1 and key not in last_run:
                if skip_today.get(date):
                    print("\n[{:02d}:{:02d}] 補充繰越のためスキップ中".format(mh1, mm1))
                    log_event("朝1回目", "SKIP", "補充繰越によるスキップ中")
                else:
                    pattern = check_and_alert_if_full(ser, "朝1回目", CMD_ALERT_REMINDER)
                    morning1_pattern[date] = pattern
                last_run[key] = True

            # 朝2回目 チェック＋アラート（1.1のときのみ送信）
            # 朝1回目が 1.0 か 0.1（片方だけ服用済み）だった場合は
            #           朝2回目のチェック自体をスキップする。
            #           0.0（両方服用済み）の場合はスキップせず通常通りチェックする。
            key = (date, mh2, mm2)
            if h == mh2 and m == mm2 and key not in last_run:
                if skip_today.get(date):
                    print("\n[{:02d}:{:02d}] 補充繰越のためスキップ中".format(mh2, mm2))
                    log_event("朝2回目", "SKIP", "補充繰越によるスキップ中")
                elif morning1_pattern.get(date) in ("1.0", "0.1"):
                    print("\n[{:02d}:{:02d}] 朝1回目で片方服用済み（{}）を確認済み → スキップ".format(
                        mh2, mm2, morning1_pattern.get(date)))
                    log_event("朝2回目", "SKIP", "朝1回目で片方服用済みを確認済み")
                else:
                    check_and_alert_if_full(ser, "朝2回目", CMD_ALERT_MORNING)
                last_run[key] = True

            # ★B案: 補充繰越スキップ中は、告知も含めて何もしない。
            key = (date, nb_h, nb_m)
            if h == nb_h and m == nb_m and key not in last_run:
                if skip_today.get(date):
                    print("\n[{:02d}:{:02d}] 補充繰越のためスキップ中（お知らせも送信しません）".format(nb_h, nb_m))
                    log_event("夕の時間告知", "SKIP", "補充繰越によるスキップ中")
                else:
                    announce_time(ser, "夕の時間告知", CMD_TIME_ANNOUNCE)
                last_run[key] = True

            # 夕1回目 チェック＋リマインダー（0.0なら夕2回目をスキップ）
            key = (date, nh1, nm1)
            if h == nh1 and m == nm1 and key not in last_run:
                if skip_today.get(date):
                    print("\n[{:02d}:{:02d}] 補充繰越のためスキップ中".format(nh1, nm1))
                    log_event("夕1回目", "SKIP", "補充繰越によるスキップ中")
                else:
                    pattern = check_and_alert(ser, "夕1回目", CMD_ALERT_REMINDER)
                    night1_pattern[date] = pattern
                last_run[key] = True

            # 夕2回目 チェック＋アラート
            key = (date, nh2, nm2)
            if h == nh2 and m == nm2 and key not in last_run:
                if skip_today.get(date):
                    print("\n[{:02d}:{:02d}] 補充繰越のためスキップ中".format(nh2, nm2))
                    log_event("夕2回目", "SKIP", "補充繰越によるスキップ中")
                elif night1_pattern.get(date) == "0.0":
                    print("\n[{:02d}:{:02d}] 夕1回目で全服用済み(0.0)を確認済み → スキップ".format(nh2, nm2))
                    log_event("夕2回目", "SKIP", "夕1回目で0.0確認済み")
                else:
                    check_and_alert(ser, "夕2回目", CMD_ALERT_NIGHT)
                last_run[key] = True


            key = (date, rb_h, rb_m)
            if h == rb_h and m == rb_m and key not in last_run:
                if skip_today.get(date):
                    skip_today[date] = False   # 繰越しスキップを解除（通常運転へ復帰）
                    print("\n  → 補充のお知らせ時刻になりました。ここから通常運転に戻ります。")
                    log_event("補充繰越", "-", "補充のお知らせ時刻で繰越しスキップ解除")
                announce_time(ser, "補充の時間告知", CMD_REFILL_ANNOUNCE)
                last_run[key] = True

            # 補充確認1回目
            key = (date, rh1, rm1)
            if h == rh1 and m == rm1 and key not in last_run:
                check_refill(ser, "補充確認1回目", CMD_ALERT_REFILL)
                last_run[key] = True

            key = (date, rh2, rm2)
            if h == rh2 and m == rm2 and key not in last_run:
                pattern = check_refill(ser, "補充確認2回目", CMD_ALERT_REFILL)
                last_refill2_pattern = pattern
                last_refill2_date    = date
                last_run[key] = True


            time.sleep(10)
    except KeyboardInterrupt:
        print("\n[常駐モード] 終了します（Ctrl+C）")
    finally:
        close_esp32_serial(ser)   # 常駐終了時に接続を閉じる


if __name__ == "__main__":
    main()