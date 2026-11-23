"""EcoFlow unofficial app-cloud client (login + MQTT), exposed through Qt signals."""
from __future__ import annotations

import base64
import json
import random
import ssl
import threading
import time
import uuid
from dataclasses import dataclass

import paho.mqtt.client as mqtt
import requests
from PySide6.QtCore import QObject, Signal

POLL_FAST = 3    # window open and visible
POLL_SLOW = 20   # minimized to tray
MIN_EMIT_GAP = 0.5  # the unit pushes partial state ~every second; coalesce
STALE_SECONDS = 60  # no reply for this long -> reconnect


@dataclass
class Telemetry:
    ts: float
    soc: float
    in_w: float       # total input (AC + solar + ...)
    out_w: float      # total output
    ac_in_w: float
    ac_out_w: float
    cfg_limit: int    # configured max AC charging power
    temp: float
    dsg_min: int      # estimated discharge time remaining, minutes
    chg_min: int      # estimated time to full, minutes
    grid: bool = True # mains (AC input voltage) present

    @property
    def charging(self) -> bool:
        return self.in_w > self.out_w and self.soc < 99.5


USED_KEYS = frozenset({
    "ems.f32LcdShowSoc", "ems.lcdShowSoc", "pd.wattsInSum", "pd.wattsOutSum", "inv.inputWatts", "inv.outputWatts",
    "inv.cfgSlowChgWatts", "bmsMaster.temp", "ems.dsgRemainTime", "ems.chgRemainTime", "inv.acInVol"})


def parse_quota(q: dict) -> Telemetry | None:
    def g(k, default=0):
        v = q.get(k)
        return default if v is None else v
    # Never build a sample from partial state (missing fields would read as 0 W)
    essentials = ("pd.wattsInSum", "pd.wattsOutSum", "inv.cfgSlowChgWatts")
    if not all(k in q for k in essentials) or not ("ems.f32LcdShowSoc" in q or "ems.lcdShowSoc" in q):
        return None
    return Telemetry(
        ts=time.time(),
        soc=float(g("ems.f32LcdShowSoc", g("ems.lcdShowSoc"))),
        in_w=float(g("pd.wattsInSum")),
        out_w=float(g("pd.wattsOutSum")),
        ac_in_w=float(g("inv.inputWatts")),
        ac_out_w=float(g("inv.outputWatts")),
        cfg_limit=int(g("inv.cfgSlowChgWatts")),
        temp=float(g("bmsMaster.temp")),
        dsg_min=int(g("ems.dsgRemainTime")),
        chg_min=int(g("ems.chgRemainTime")),
        grid=(float(q["inv.acInVol"]) >= 90_000) if "inv.acInVol" in q else float(g("inv.inputWatts")) >= 5,
    )


def login(host: str, email: str, password: str) -> tuple[str, str]:
    r = requests.post(
        f"https://{host}/auth/login",
        headers={"lang": "en_US", "content-type": "application/json"},
        json={"email": email, "password": base64.b64encode(password.encode()).decode(),
              "scene": "IOT_APP", "userType": "ECOFLOW"},
        timeout=20,
    )
    r.raise_for_status()
    j = r.json()
    if str(j.get("message", "")).lower() != "success":
        raise RuntimeError(f"Login failed: {j.get('message')}")
    return j["data"]["token"], j["data"]["user"]["userId"]


def mqtt_creds(host: str, token: str, user_id: str):
    r = requests.get(
        f"https://{host}/iot-auth/app/certification",
        headers={"lang": "en_US", "authorization": f"Bearer {token}"},
        params={"userId": user_id}, timeout=20,
    )
    r.raise_for_status()
    j = r.json()
    if str(j.get("message", "")).lower() != "success":
        raise RuntimeError(f"MQTT credentials failed: {j.get('message')}")
    d = j["data"]
    return d["url"], int(d["port"]), d["certificateAccount"], d["certificatePassword"]


class EcoflowClient(QObject):
    telemetry = Signal(object)   # Telemetry
    status = Signal(str)         # human-readable connection status
    online = Signal(bool)        # device reachable

    def __init__(self, host: str, email: str, password: str, sn: str):
        super().__init__()
        self.host, self.email, self.password, self.sn = host, email, password, sn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._client: mqtt.Client | None = None
        self._uid = ""
        self._quota: dict = {}
        self._seeded = False        # True once a full latestQuotas reply of THIS connection filled _quota
        self._last_reply = 0.0
        self._poll = POLL_SLOW
        self._wake = threading.Event()
        self._last_emit = 0.0

    # ---- lifecycle -------------------------------------------------
    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="ecoflow-client")
        self._thread.start()

    def set_poll_interval(self, seconds: float):
        """Takes effect immediately (wakes the polling loop)."""
        if seconds != self._poll:
            self._poll = seconds
            self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self._teardown()

    # ---- commands --------------------------------------------------
    def set_ac_limit(self, watts: int) -> bool:
        c = self._client
        if not c or not c.is_connected():
            return False
        payload = {"from": "ef-scheduler", "id": str(999900000 + random.randint(10000, 99999)),
                   "version": "1.0", "moduleType": 0, "operateType": "TCP",
                   "params": {"slowChgPower": int(watts), "id": 69}}
        c.publish(f"/app/{self._uid}/{self.sn}/thing/property/set", json.dumps(payload), qos=1)
        for delay in (2, 6, 12):  # the unit applies the change within seconds; re-read state to confirm quickly
            threading.Timer(delay, self.request_state).start()
        return True

    def request_state(self):
        c = self._client
        if c and c.is_connected():
            c.publish(f"/app/{self._uid}/{self.sn}/thing/property/get", json.dumps({
                "from": "ef-scheduler", "id": str(random.randint(10**8, 10**9)), "version": "1.1",
                "moduleType": 0, "operateType": "latestQuotas", "params": {}}), qos=1)

    # ---- internals -------------------------------------------------
    def _run(self):
        backoff = 5
        while not self._stop.is_set():
            try:
                self.status.emit("Signing in...")
                token, self._uid = login(self.host, self.email, self.password)
                url, port, user, pwd = mqtt_creds(self.host, token, self._uid)
                self._connect(url, port, user, pwd)
                backoff = 5
                self._last_reply = time.time()
                while not self._stop.is_set():
                    self.request_state()
                    self._wake.wait(self._poll)
                    self._wake.clear()
                    if self._stop.is_set():
                        return
                    if time.time() - self._last_reply > STALE_SECONDS:
                        raise TimeoutError("no data from EcoFlow cloud")
            except Exception as e:  # noqa: BLE001 - reconnect on anything
                self.status.emit(f"Offline: {e}")
                self.online.emit(False)
                self._teardown()
                if self._stop.wait(backoff):
                    return
                backoff = min(backoff * 2, 300)
        self._teardown()

    def _teardown(self):
        c, self._client = self._client, None
        if c:
            try:
                c.loop_stop()
                c.disconnect()
            except Exception:
                pass

    def _connect(self, url, port, user, pwd):
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                        client_id=f"ANDROID_{uuid.uuid4().hex.upper()}_{self._uid}", clean_session=True)
        c.username_pw_set(user, pwd)
        c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        c.on_connect = self._on_connect
        c.on_message = self._on_message
        self._client = c
        self._quota, self._seeded = {}, False      # state kept across a sleep/reconnect is stale: start from scratch
        c.connect(url, port, keepalive=15)
        c.loop_start()
        for _ in range(100):  # wait up to 10 s for CONNACK
            if c.is_connected():
                return
            time.sleep(0.1)
        raise TimeoutError("MQTT connect timeout")

    def _on_connect(self, c, _u, _f, rc, _p=None):
        if rc == 0:
            c.subscribe([(f"/app/device/property/{self.sn}", 1),
                         (f"/app/{self._uid}/{self.sn}/thing/property/get_reply", 1)])
            self.status.emit("Connected")
        else:
            self.status.emit(f"MQTT refused: {rc}")

    def _on_message(self, _c, _u, msg):
        try:
            body = json.loads(msg.payload)
        except ValueError:
            return
        is_reply = msg.topic.endswith("get_reply") and body.get("operateType") == "latestQuotas"
        if is_reply:
            data = body.get("data", {})
            self._last_reply = time.time()
            if int(data.get("online", 0)) != 1:
                self._quota, self._seeded = {}, False
                self.online.emit(False)
                self.status.emit("Device offline (cloud reachable)")
                return
            self._quota = dict(data.get("quotaMap", {}))
            self._seeded = True
        else:
            p = body.get("params")
            # the unit pushes a constant stream of unrelated 'kit.*' messages - ignore those
            if isinstance(p, dict) and USED_KEYS.intersection(p):
                if not self._seeded:
                    return        # a push alone would be merged into old/empty state and recorded as a fresh sample
                self._quota.update(p)
            else:
                return
        now = time.time()
        if not is_reply and now - self._last_emit < MIN_EMIT_GAP:
            return  # state is merged above; the next message carries it
        self._last_emit = now
        t = parse_quota(self._quota)
        if t:
            self.online.emit(True)
            self.status.emit("Connected")
            self.telemetry.emit(t)
