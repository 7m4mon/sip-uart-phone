# sip_uart_phone

PJSUA2 と USB-UART を使って、マイコンから SIP 電話の発着信を制御するための Python プログラムです。

Raspberry Pi 側で `sip_uart_phone.py` を動かし、Arduino などのマイコン側から UART コマンドを送ることで、内線への発信、着信応答、切断を行います。

相手側のパネル（マイコン側スケッチ）は、`morse_phone_panel.ino` のリポジトリを参照してください。

---

## 概要

このプログラムは、PJSUA2 を用いて SIP アカウントを生成し、USB-Serial 経由で受け取ったコマンドに応じて通話制御を行います。

主な機能は以下の通りです。

- UART から受け取った番号で SIP 発信
- 着信時の応答
- 通話切断
- 着信中のリング通知を UART で送出
- 通話成立／終了通知を UART で送出
- 通話確立後にマイク・スピーカーを自動接続

---

## 構成

### Raspberry Pi 側

- `sip_uart_phone.py`
- `pjsua2` を利用して SIP 通話を制御
- USB-UART でマイコンと接続

### マイコン側

- `morse_phone_panel.ino`
- ボタンやモールス入力などで番号入力・発信・応答・切断を行う

---

## UART プロトコル

### MCU → Raspberry Pi

1行ごとに改行付きで送信します。

- `D<number>\n`  
  発信  
  例: `D31`

- `H\n`  
  切断

- `A\n`  
  着信応答

### Raspberry Pi → MCU

マイコン側で1文字ずつ処理する前提のため、改行は付きません。

- `R`  
  着信中（100 ms 周期で送信）

- `C`  
  通話成立（CONFIRMED）

- `E`  
  通話終了（DISCONNECTED）

---

## 動作イメージ

### 発信

1. マイコン側で番号を入力
2. 発信ボタン押下
3. MCU から `D31\n` のようなコマンドを送信
4. Raspberry Pi 側が `sip:31@<SIP_DOMAIN>` に発信
5. 通話成立時に Raspberry Pi から MCU へ `C` を送信

### 着信

1. Raspberry Pi 側で SIP 着信を受信
2. 着信中は MCU に `R` を周期送信
3. MCU 側で応答操作を行う
4. MCU から `A\n` を送信
5. Raspberry Pi 側が 200 OK で応答し、通話成立後 `C` を送信

### 切断

- MCU から `H\n` を送ると通話を切断
- 通話終了時は Raspberry Pi から `E` を送信

---

## 必要なもの

- Raspberry Pi
- Python 3
- PJSUA2
- pyserial
- USB-Serial 接続されたマイコン
- SIP サーバー（例: Asterisk）

---

## インストール

PJSUA / PJSUA2 のインストール方法は、`pjsua_install_summary.docx` を参照してください。 

---

## 設定

`sip_uart_phone.py` 冒頭のユーザー設定を書き換えてください。

```python
SIP_DOMAIN = "127.0.0.1"
SIP_USER = "251"
SIP_PASS = "251"

SERIAL_PORT = "/dev/ttyACM0"
SERIAL_BAUD = 115200

CAPTURE_DEV_ID = -1
PLAYBACK_DEV_ID = -1
```

### 主な設定項目

- `SIP_DOMAIN`  
  SIP サーバーのアドレス

- `SIP_USER`  
  SIP ユーザー名

- `SIP_PASS`  
  SIP パスワード

- `SERIAL_PORT`  
  接続する USB-Serial デバイス  
  例: `/dev/ttyUSB0` または `/dev/ttyACM0`

- `SERIAL_BAUD`  
  UART 通信速度

- `CAPTURE_DEV_ID`  
  録音デバイス ID  
  `-1` の場合はデフォルトデバイス

- `PLAYBACK_DEV_ID`  
  再生デバイス ID  
  `-1` の場合はデフォルトデバイス

---

## 実行方法

```bash
python3 sip_uart_phone.py
```

起動後、UART からのコマンド待ちになります。

---

## ログ例

```text
[12:34:56] [UART] opened /dev/ttyACM0 @ 115200 bps
[12:34:57] [SIP] account created: sip:251@127.0.0.1
[12:35:10] [UART RX] D31
[12:35:10] [CALL] dial -> sip:31@127.0.0.1
[12:35:12] [CALL] CONFIRMED
[12:35:12] [AUDIO] connected
```

---

## 備考

- Raspberry Pi から MCU への通知は改行なしの1文字送信です。
- 着信中の `R` は 100 ms 周期で送信されます。
- 通話成立時には音声デバイスを接続し、マイクとスピーカーを有効にします。
- すでに通話中の状態で新たに発信コマンドを受けた場合、一旦既存通話を切断してから新しい発信を行います。

---

## 関連

- Raspberry Pi 側アプリ: `sip_uart_phone.py`
- マイコン側パネル: `morse_phone_panel.ino`
- PJSUA インストール手順: `pjsua_install_summary.docx`

---

## ライセンス

MIT
