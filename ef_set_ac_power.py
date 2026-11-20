"""Set EcoFlow Delta Pro (original) max AC charging power via the unofficial app cloud API.

Usage:
    Fill in .env (EF_EMAIL, EF_PASSWORD, EF_SN, EF_API_HOST), then:
    python ef_set_ac_power.py 626

Optional: EF_API_HOST (default api.ecoflow.com; EU accounts may need api-e.ecoflow.com)

Protocol (from tolwi/hassio-ecoflow-cloud):
  POST https://<host>/auth/login                      -> token, userId
  GET  https://<host>/iot-auth/app/certification      -> MQTT url/port/user/password
  MQTT publish /app/<userId>/<sn>/thing/property/set  {"moduleType":0,"operateType":"TCP",
                                                       "params":{"slowChgPower":W,"id":69}}
  Device state is pushed on /app/device/property/<sn> (key "inv.cfgSlowChgWatts").
"""
import base64
import json
import os
import random
import ssl
import sys
import time
import uuid

import paho.mqtt.client as mqtt
import requests
from dotenv import load_dotenv

MIN_W, MAX_W = 200, 2900  # Delta Pro (original) range per hassio-ecoflow-cloud


def login(host, email, password):
    r = requests.post(
        f"https://{host}/auth/login",
        headers={"lang": "en_US", "content-type": "application/json"},
        json={
            "email": email,
            "password": base64.b64encode(password.encode()).decode(),
            "scene": "IOT_APP",
            "userType": "ECOFLOW",
        },
        timeout=20,
    )
    r.raise_for_status()
    j = r.json()
    if str(j.get("message", "")).lower() != "success":
        sys.exit(f"Login failed: {j.get('message')} (code {j.get('code')})")
    return j["data"]["token"], j["data"]["user"]["userId"]


def mqtt_creds(host, token, user_id):
    r = requests.get(
        f"https://{host}/iot-auth/app/certification",
        headers={"lang": "en_US", "authorization": f"Bearer {token}"},
        params={"userId": user_id},
        timeout=20,
    )
    r.raise_for_status()
    j = r.json()
    if str(j.get("message", "")).lower() != "success":
        sys.exit(f"MQTT cert request failed: {j.get('message')}")
    d = j["data"]
    return d["url"], int(d["port"]), d["certificateAccount"], d["certificatePassword"]


def find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find_key(v, key)
            if r is not None:
                return r
    return None


def main():
    load_dotenv()
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        sys.exit(__doc__)
    watts = int(sys.argv[1])
    if not MIN_W <= watts <= MAX_W:
        sys.exit(f"Watts must be {MIN_W}-{MAX_W}")

    try:
        email, password, sn = os.environ["EF_EMAIL"], os.environ["EF_PASSWORD"], os.environ["EF_SN"]
    except KeyError as e:
        sys.exit(f"Missing env var {e}")
    host = os.environ.get("EF_API_HOST", "api.ecoflow.com")

    token, user_id = login(host, email, password)
    url, port, user, pwd = mqtt_creds(host, token, user_id)
    print(f"Logged in, MQTT broker {url}:{port}")

    state = {"confirmed": False, "current": None}
    data_topic = f"/app/device/property/{sn}"
    set_topic = f"/app/{user_id}/{sn}/thing/property/set"
    reply_topic = f"/app/{user_id}/{sn}/thing/property/set_reply"

    def on_connect(c, _u, _f, rc, _p=None):
        if rc != 0:
            sys.exit(f"MQTT connect failed: {rc}")
        c.subscribe([(data_topic, 1), (reply_topic, 1)])
        payload = {
            "from": "ef-script",
            "id": str(999900000 + random.randint(10000, 99999)),
            "version": "1.0",
            "moduleType": 0,
            "operateType": "TCP",
            "params": {"slowChgPower": watts, "id": 69},
        }
        c.publish(set_topic, json.dumps(payload), qos=1)
        print(f"Sent: AC charging power -> {watts} W")

    def on_message(_c, _u, msg):
        try:
            body = json.loads(msg.payload)
        except ValueError:
            return
        if msg.topic == reply_topic:
            print("Reply:", body)
        v = find_key(body, "inv.cfgSlowChgWatts")
        if v is not None:
            state["current"] = v
            if v == watts:
                state["confirmed"] = True

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"ANDROID_{uuid.uuid4().hex.upper()}_{user_id}",
        clean_session=True,
    )
    client.username_pw_set(user, pwd)
    client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(url, port, keepalive=15)
    client.loop_start()

    deadline = time.time() + 30
    while time.time() < deadline and not state["confirmed"]:
        time.sleep(0.5)
    client.loop_stop()
    client.disconnect()

    if state["confirmed"]:
        print(f"CONFIRMED: device reports inv.cfgSlowChgWatts = {watts}")
    else:
        print(f"Not confirmed in 30 s (last reported: {state['current']}). "
              "Check the app; the device may only push state periodically.")
        sys.exit(1)


if __name__ == "__main__":
    main()
