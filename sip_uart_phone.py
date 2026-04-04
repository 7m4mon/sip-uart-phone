#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sip_uart_phone.py
PJSUA2 + USB-Serial で発着信制御する簡易 SIP Phone

UART protocol (from MCU -> RPi):
  D<number>\n  : dial extension number, e.g. D31
  H\n          : hangup
  A\n          : answer incoming call

UART protocol (from RPi -> MCU):
  R            : ringing (100 ms period)
  C            : call CONFIRMED (connected)
  E            : call DISCONNECTED (ended)

※ RPi -> MCU は、マイコン側で1文字ごとに処理する前提のため改行なし
"""

import time
import queue
import threading
from dataclasses import dataclass

import serial
import pjsua2 as pj


# =========================
# User settings
# =========================
SIP_DOMAIN = "127.0.0.1"
SIP_USER = "251"
SIP_PASS = "251"

SERIAL_PORT = "/dev/ttyACM0"
SERIAL_BAUD = 115200

CAPTURE_DEV_ID = -1
PLAYBACK_DEV_ID = -1

RING_NOTIFY_INTERVAL_S = 0.10


def log(msg: str):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


@dataclass
class CmdDial:
    number: str


@dataclass
class CmdHangup:
    pass


@dataclass
class CmdAnswer:
    pass


class UartThread(threading.Thread):
    def __init__(self, port: str, baud: int, q_cmd: queue.Queue):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.q_cmd = q_cmd
        self.ser = None
        self.stop_ev = threading.Event()
        self.tx_lock = threading.Lock()

    def open(self):
        self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
        log(f"[UART] opened {self.port} @ {self.baud} bps")

    def write_bytes(self, s: str):
        """
        RPi -> MCU 送信用。
        MCU 側は 1 文字ごとに処理するため、改行は付けない。
        """
        if not self.ser:
            return

        with self.tx_lock:
            try:
                self.ser.write(s.encode("ascii", errors="ignore"))
            except Exception as e:
                log(f"[UART] write error: {e}")

    def stop(self):
        self.stop_ev.set()

    def run(self):
        buf = b""

        try:
            self.open()
        except Exception as e:
            log(f"[UART] open error: {e}")
            return

        while not self.stop_ev.is_set():
            try:
                data = self.ser.read(256)
                if not data:
                    continue

                buf += data

                while b"\n" in buf:
                    raw_line, buf = buf.split(b"\n", 1)
                    line = raw_line.decode(errors="ignore").strip()

                    if not line:
                        continue

                    log(f"[UART RX] {line}")

                    if line.startswith("D"):
                        self.q_cmd.put(CmdDial(line[1:]))
                    elif line == "H":
                        self.q_cmd.put(CmdHangup())
                    elif line == "A":
                        self.q_cmd.put(CmdAnswer())

            except Exception as e:
                log(f"[UART] read error: {e}")
                time.sleep(0.05)


class Call(pj.Call):
    def __init__(self, acc, cid=pj.PJSUA_INVALID_ID, app=None):
        super().__init__(acc, cid)
        self.app = app

    def onCallState(self, prm):
        ci = self.getInfo()
        log(f"[CALL] {ci.stateText}")
        if self.app:
            self.app.on_call_state(ci.state)

    def onCallMediaState(self, prm):
        if self.app:
            self.app.on_call_media()


class Account(pj.Account):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def onIncomingCall(self, prm):
        log("[CALL] incoming")
        self.app.incoming_call(prm.callId)


class App:
    def __init__(self):
        self.ep = pj.Endpoint()
        self.acc = None
        self.call = None
        self.q_cmd = queue.Queue()
        self.uart = UartThread(SERIAL_PORT, SERIAL_BAUD, self.q_cmd)
        self.ringing = False
        self.last_ring = 0.0

    def init(self):
        self.ep.libCreate()

        cfg = pj.EpConfig()
        cfg.logConfig.level = 4
        self.ep.libInit(cfg)

        self.ep.transportCreate(pj.PJSIP_TRANSPORT_UDP, pj.TransportConfig())
        self.ep.libStart()

        adm = self.ep.audDevManager()
        if CAPTURE_DEV_ID != -1:
            adm.setCaptureDev(CAPTURE_DEV_ID)
        if PLAYBACK_DEV_ID != -1:
            adm.setPlaybackDev(PLAYBACK_DEV_ID)

        acfg = pj.AccountConfig()
        acfg.idUri = f"sip:{SIP_USER}@{SIP_DOMAIN}"
        acfg.regConfig.registrarUri = f"sip:{SIP_DOMAIN}"
        acfg.sipConfig.authCreds.append(
            pj.AuthCredInfo("digest", "*", SIP_USER, 0, SIP_PASS)
        )

        self.acc = Account(self)
        self.acc.create(acfg)

        log(f"[SIP] account created: {acfg.idUri}")

    def incoming_call(self, cid):
        self.call = Call(self.acc, cid, self)
        self.ringing = True

    def dial(self, num: str):
        if self.call:
            self.hangup()

        uri = f"sip:{num}@{SIP_DOMAIN}"
        log(f"[CALL] dial -> {uri}")

        self.call = Call(self.acc, pj.PJSUA_INVALID_ID, self)
        self.call.makeCall(uri, pj.CallOpParam(True))

    def answer(self):
        if not self.call:
            return

        log("[CALL] answer")
        prm = pj.CallOpParam()
        prm.statusCode = 200
        self.call.answer(prm)
        self.ringing = False

    def hangup(self):
        if self.call:
            log("[CALL] hangup")
            self.call.hangup(pj.CallOpParam())

        self.call = None
        self.ringing = False

    def on_call_state(self, state):
        if state == pj.PJSIP_INV_STATE_CONFIRMED:
            self.uart.write_bytes("C")
            self.connect_audio()

        elif state == pj.PJSIP_INV_STATE_DISCONNECTED:
            self.uart.write_bytes("E")
            self.call = None
            self.ringing = False

    def on_call_media(self):
        self.connect_audio()

    def connect_audio(self):
        if not self.call:
            return

        ci = self.call.getInfo()

        for i, m in enumerate(ci.media):
            if (
                m.type == pj.PJMEDIA_TYPE_AUDIO
                and m.status == pj.PJSUA_CALL_MEDIA_ACTIVE
            ):
                am = pj.AudioMedia.typecastFromMedia(self.call.getMedia(i))
                adm = self.ep.audDevManager()

                am.startTransmit(adm.getPlaybackDevMedia())
                adm.getCaptureDevMedia().startTransmit(am)

                log("[AUDIO] connected")
                return

    def loop(self):
        self.uart.start()

        while True:
            while not self.q_cmd.empty():
                cmd = self.q_cmd.get()

                if isinstance(cmd, CmdDial):
                    self.dial(cmd.number)
                elif isinstance(cmd, CmdHangup):
                    self.hangup()
                elif isinstance(cmd, CmdAnswer):
                    self.answer()

            now = time.time()
            if self.ringing and (now - self.last_ring) > RING_NOTIFY_INTERVAL_S:
                self.uart.write_bytes("R")
                self.last_ring = now

            time.sleep(0.01)


def main():
    app = App()
    app.init()
    app.loop()


if __name__ == "__main__":
    main()