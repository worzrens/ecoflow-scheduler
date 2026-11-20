"""Dump raw device messages for ~25 s to probe_dump.jsonl (dev tool)."""
import json, os, ssl, time, uuid, random
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from ef_set_ac_power import login, mqtt_creds

load_dotenv()
sn = os.environ["EF_SN"]; host = os.environ.get("EF_API_HOST", "api.ecoflow.com")
token, uid = login(host, os.environ["EF_EMAIL"], os.environ["EF_PASSWORD"])
url, port, user, pwd = mqtt_creds(host, token, uid)
out = open("probe_dump.jsonl", "w", encoding="utf-8")
def on_connect(c, *_):
    c.subscribe([(f"/app/device/property/{sn}", 1), (f"/app/{uid}/{sn}/thing/property/get_reply", 1)])
    c.publish(f"/app/{uid}/{sn}/thing/property/get", json.dumps({"from": "probe", "id": str(random.randint(10**8, 10**9)), "version": "1.1", "moduleType": 0, "operateType": "latestQuotas", "params": {}}), qos=1)
def on_message(c, u, m):
    out.write(json.dumps({"t": time.time(), "topic": m.topic, "body": m.payload.decode("utf-8", "ignore")}) + "\n"); out.flush()
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"ANDROID_{uuid.uuid4().hex.upper()}_{uid}")
c.username_pw_set(user, pwd); c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
c.on_connect = on_connect; c.on_message = on_message
c.connect(url, port, 15); c.loop_start(); time.sleep(25); c.loop_stop()
