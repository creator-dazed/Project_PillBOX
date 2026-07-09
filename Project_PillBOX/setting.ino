#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>   // GAS(https)送信に必要
#include "KT403A_Player.h"      // https://github.com/Seeed-Studio/Seeed_Serial_MP3_Player

// FreeRTOS
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

// 1=テストコマンド有効 / 0=無効
#define ENABLE_SERIAL_TEST 1

// =====================================================
// PillBox クラス：薬箱の「状態」と「振る舞い」を全部ここに閉じ込める
// =====================================================
class PillBox {
public:
    void begin() {
        pinMode(SENSOR_PIN, INPUT_PULLUP);

        mp3Init();
        connectWiFi();

        gasQueue_ = xQueueCreate(GAS_QUEUE_LEN, sizeof(GasEvent));
        if (gasQueue_ == nullptr) {
            Serial.println("[致命的] queue作成失敗。3秒後に再起動します");
            delay(3000);
            ESP.restart();
        }

        BaseType_t ok = xTaskCreate(
            networkTaskEntry_,
            "gasNetwork",
            12288,
            this,
            1,
            &netTaskHandle_);
        if (ok != pdPASS) {
            Serial.println("[致命的] networkTask起動失敗。3秒後に再起動します");
            delay(3000);
            ESP.restart();
        }

        Serial.println("PiLLBOX 起動完了");
    }

    //メインloop側
    void update() {
        if (Serial.available()) {
            handleSerialByte(Serial.read());
        }
        checkLidSensor();    // 磁気センサー監視（常に約50ms周期で回り続ける）
    }

private:
    // -----------------------------------------------------
    // 設定（書き換えない定数：クラス定数にまとめる）
    // -----------------------------------------------------
    static constexpr const char* SSID_     = "xxxx";
    static constexpr const char* PASSWORD_ = "xxxx";
    static constexpr const char* GAS_URL   =
        "https://script.google.com/xxxx/";

    static constexpr int GAS_MAX_RETRY = 3;

    static constexpr int GAS_QUEUE_LEN = 5;   //送信待ちイベントの最大保持数

    static constexpr byte CMD_MISS_MORNING = 0x01;   // 朝アラート(8:30)
    static constexpr byte CMD_MISS_EVENING = 0x02;   // 夜アラート(19:30)
    static constexpr byte CMD_REMINDER     = 0x03;   // リマインダー(8:15/19:15)
    static constexpr byte CMD_REFILL_MISS  = 0x04;   // 補充忘れ(20:15)
    static constexpr byte CMD_NOTIFY_DOSE  = 0x05;   // 服薬お知らせ
    static constexpr byte CMD_NOTIFY_REFILL= 0x06;   // 補充案内

    static constexpr int SENSOR_PIN     = 4;         // 磁気センサー
    static constexpr int LID_OPEN_STATE = HIGH;      // 蓋オープン時の値。逆ならLOW

    static constexpr int MP3_RX_PIN     = 3;         // ESP RX ← KT403A TX
    static constexpr int MP3_TX_PIN     = 1;         // ESP TX → KT403A RX

    // MP3トラック番号（/MP3/000X.mp3 に対応）
    static constexpr int TRACK_REMINDER = 1;   // 0001 お薬の時間です
    static constexpr int TRACK_REFILL   = 2;   // 0002 お薬をセットしてください
    static constexpr int TRACK_MISSED   = 3;   // 0003 飲み忘れていませんか？
    static constexpr int TRACK_BELL     = 4;   // 0004 ピピピッ(合図音)

    static constexpr unsigned long LID_STABLE_MS = 1000; // この時間同じ値なら状態確定(１秒)

    struct GasEvent {
        char    event[32];    // 例: "missed_morning"
        char    detail[24];   // 例: "no_open" / "camera" / "in_window"
        uint8_t maxRetry;     // 3=重要イベント / 2=open,close
    };

    // -----------------------------------------------------
    // 状態（グローバル変数はすべてクラス内に閉じ込め）
    // -----------------------------------------------------
    HardwareSerial          mp3Serial{1};   // KT403A用のUART1
    KT403A<HardwareSerial>  mp3Player;

    // 以下はメインタスクだけが触る変数
    int           lidRawLast     = -1;
    unsigned long lidRawSince    = 0;
    int           lidState       = LID_OPEN_STATE;
    bool          lidInitialized = false;

    // ★14 タスク間連携用
    QueueHandle_t     gasQueue_       = nullptr;
    TaskHandle_t      netTaskHandle_  = nullptr;

    // -----------------------------------------------------
    // KT403A MP3 制御（メインタスク専用。networkTaskからは呼ばない）
    // -----------------------------------------------------
    void mp3Init() {
        mp3Serial.begin(9600, SERIAL_8N1, MP3_RX_PIN, MP3_TX_PIN);
        delay(1000);
        mp3Player.init(mp3Serial);
        delay(500);
        Serial.println("KT403A 初期化完了");
    }
    void mp3Play(int track) { mp3Player.playSongMP3(track); }
    void soundReminder() { mp3Play(TRACK_REMINDER); }   // 0001 お知らせ
    void soundRefill()   { mp3Play(TRACK_REFILL);   }   // 0002 セット
    void soundMissed()   { mp3Play(TRACK_MISSED);   }   // 0003 飲み忘れ
    void soundBell()      { mp3Play(TRACK_BELL); }      // 0004 ピピピッ(合図音)

    //  信号受信の合図(BELL)と本編音声の間隔。KT403Aは前の再生命令が
    //  終わる前に次を受け取ると2つ目を無視するため、必ず間を空ける
    static constexpr unsigned long CHIME_GAP_MS = 300;

    // -----------------------------------------------------
    // WiFi接続（★14 起動時のbegin()と、以降はnetworkTaskからのみ呼ぶ）
    // -----------------------------------------------------
    void connectWiFi() {
        if (WiFi.status() == WL_CONNECTED) return;
        Serial.println("WiFi接続中...");
        WiFi.begin(SSID_, PASSWORD_);
        int count = 0;
        while (WiFi.status() != WL_CONNECTED && count < 20) {
            delay(500);
            count++;
        }
        // 省電力のタイマー割り込みが lwIP と競合してクラッシュするため無効化
        WiFi.setSleep(false);
        Serial.println(WiFi.status() == WL_CONNECTED ? "WiFi接続成功" : "WiFi接続失敗");
    }

    // -----------------------------------------------------
    // ★14 GAS送信の「依頼」側。メインタスクから呼ぶ（即return）。
    //     実際の送信はnetworkTaskがキューから取り出して行う。
    // -----------------------------------------------------
    void enqueueGAS_(const char* event, const char* detail, uint8_t maxRetry) {
        GasEvent ev;
        strlcpy(ev.event,  event,  sizeof(ev.event));
        strlcpy(ev.detail, detail, sizeof(ev.detail));
        ev.maxRetry = maxRetry;

        if (xQueueSend(gasQueue_, &ev, 0) != pdTRUE) {
            Serial.println("[警告] GAS送信キュー満杯のためイベント破棄: " + String(event));
        }
    }
    void queueToGAS(const String& event, const String& detail) {
        enqueueGAS_(event.c_str(), detail.c_str(), GAS_MAX_RETRY);
    }
    void queueToGASOnce(const String& event, const String& detail) {
        enqueueGAS_(event.c_str(), detail.c_str(), 2);
    }

    // -----------------------------------------------------
    // GAS Webアプリへ送信（リトライ＋応答チェック）【★14 networkTask専用】
    // -----------------------------------------------------
    bool sendToGASRetry(const String& event, const String& detail, int maxRetry) {
        connectWiFi();
        if (WiFi.status() != WL_CONNECTED) {
            Serial.println("WiFi未接続 - GAS送信スキップ");
            return false;
        }

        String payload = "{\"event\":\"" + event + "\",\"detail\":\"" + detail + "\"}";

        for (int attempt = 1; attempt <= maxRetry; attempt++) {
            WiFiClientSecure client;
            client.setInsecure();

            HTTPClient http;
            http.setTimeout(8000);
            http.begin(client, GAS_URL);
            // ★1 POSTはリダイレクトを追わない（GASは302前に記録済み）
            http.setFollowRedirects(HTTPC_DISABLE_FOLLOW_REDIRECTS);
            http.addHeader("Content-Type", "application/json");

            int    code = http.POST(payload);
            String body = (code > 0) ? http.getString() : "";
            http.end();

            if (code == 200 || code == 302) {
                Serial.println("GAS送信成功(" + String(attempt) + "回目): " + event
                               + " code=" + String(code));
                return true;
            }

            if (code >= 200) {
                Serial.println("GAS送信 応答異常: " + event + " code=" + String(code)
                               + "（再送しません）");
                return false;
            }

            Serial.println("GAS接続失敗(" + String(attempt) + "/" + String(maxRetry)
                           + "): code=" + String(code) + "（再送します）");
            vTaskDelay(pdMS_TO_TICKS(1000));
        }

        Serial.println("GAS送信 最終確認できず: " + event
                       + "（スプレッドシートを確認してください）");
        return false;
    }

    // -----------------------------------------------------
    // ★14 通信専用タスクの本体。ずっとこのループを回り続ける。
    // -----------------------------------------------------
    static void networkTaskEntry_(void* param) {
        static_cast<PillBox*>(param)->networkTaskLoop_();
    }

    void networkTaskLoop_() {
        for (;;) {
            // イベント送信。キューが空なら最大200msここで眠りCPUを手放す
            GasEvent ev;
            if (xQueueReceive(gasQueue_, &ev, pdMS_TO_TICKS(200)) == pdTRUE) {
                sendToGASRetry(String(ev.event), String(ev.detail), ev.maxRetry);
            }
            // ★15(D) CPU譲渡の保険
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }

    // -----------------------------------------------------
    // ラズパイからの信号（0x01〜0x05）を処理 ★2★13
    //   sendToGAS → queueToGAS
    //   （ここはメインタスクからのみ・ロック外なので直接呼んでよい）
    // -----------------------------------------------------
    void handlePiByte(byte b) {
        soundBell();
        delay(CHIME_GAP_MS);

        if (b == CMD_MISS_MORNING) {
            Serial.println("Piから朝アラート(0x01)");
            soundMissed();
            queueToGAS("missed_morning", "camera");
        } else if (b == CMD_MISS_EVENING) {
            Serial.println("Piから夜アラート(0x02)");
            soundMissed();
            queueToGAS("missed_evening", "camera");
        } else if (b == CMD_REMINDER) {
            Serial.println("Piからリマインダー(0x03)");
            soundMissed();
            queueToGAS("reminder", "camera");
        } else if (b == CMD_REFILL_MISS) {
            Serial.println("Piから補充忘れ(0x04)");
            soundRefill();
            queueToGAS("noset", "camera");
        } else if (b == CMD_NOTIFY_DOSE) {
            Serial.println("Piから服薬お知らせ(0x05)");
            soundReminder();
            queueToGAS("remind", "pi");
        } else if (b == CMD_NOTIFY_REFILL) {
            Serial.println("Piから補充案内(0x06)");
            soundRefill();
            queueToGAS("refill", "pi");
        } else {
            Serial.print("不明なバイト受信: 0x");
            Serial.println(b, HEX);
        }
    }

    // -----------------------------------------------------
    // 磁気センサーで蓋の開閉を検知
    //   ★17 開閉の事実だけをGASへキュー積みで報告
    // -----------------------------------------------------
    void checkLidSensor() {
        int raw           = digitalRead(SENSOR_PIN);
        unsigned long now = millis();

        if (raw != lidRawLast) {
            lidRawLast  = raw;
            lidRawSince = now;
            return;
        }
        if (now - lidRawSince < LID_STABLE_MS) return;

        if (!lidInitialized) {
            lidState       = raw;
            lidInitialized = true;
            return;
        }
        if (raw == lidState) return;

        lidState = raw;

        if (raw == LID_OPEN_STATE) {
            Serial.println("蓋オープン検知");
            queueToGASOnce("open", "");
        } else {
            Serial.println("蓋クローズ検知");
            queueToGASOnce("close", "");
        }
    }

    // -----------------------------------------------------
    // シリアル受信（テストコマンド含む）
    // -----------------------------------------------------
    void handleSerialByte(byte b) {
#if ENABLE_SERIAL_TEST
        if      (b == '1') handlePiByte(CMD_MISS_MORNING);
        else if (b == '2') handlePiByte(CMD_MISS_EVENING);
        else if (b == '5') handlePiByte(CMD_REMINDER);
        else if (b == '6') handlePiByte(CMD_REFILL_MISS);
        else if (b == '7') handlePiByte(CMD_NOTIFY_DOSE);
        else if (b == '8') handlePiByte(CMD_NOTIFY_REFILL);
        else if (b == 'b') { Serial.println("[TEST] 0001 お知らせ音"); soundReminder(); }
        else if (b == 'r') { Serial.println("[TEST] 0002 セット音");   soundRefill();   }
        else if (b == 'm') { Serial.println("[TEST] 0003 飲み忘れ音"); soundMissed();   }
        else if (b == 'n') { Serial.println("[TEST] 0004 BELL(合図音)"); soundBell(); }
        else if (b == '3') { Serial.println("[TEST] 朝 蓋開かず"); queueToGAS("missed_morning", "no_open"); }
        else if (b == '4') { Serial.println("[TEST] 夜 蓋開かず"); queueToGAS("missed_evening", "no_open"); }
        else if (b == 'g') { Serial.println("[TEST] GAS送信"); queueToGAS("open", "test"); }
        else if (b == 's') { Serial.println("[TEST] センサー生値: " + String(digitalRead(SENSOR_PIN))
                             + " (OPEN判定値=" + String(LID_OPEN_STATE) + ")"); }
        else               handlePiByte(b);
#else
        handlePiByte(b);
#endif
    }
};

// =====================================================
// setup / loop（グローバル領域に変数なし。実体は loop() 内 static）
// ★14 loop()＝メインタスクはセンサー監視と時刻判定だけ。GAS通信はnetworkTaskが担当
// =====================================================
void setup() {
    Serial.begin(115200);
}

void loop() {
    static PillBox pillbox;
    static bool    started = false;

    if (!started) {
        pillbox.begin();
        started = true;
    }

    pillbox.update();
    delay(50);
}

