"""Create/update bot Menu button to open the Mini App. Run: python bot/setup_menu.py"""
import os
import urllib.request, urllib.parse, json
from dotenv import load_dotenv

load_dotenv("backend/.env")
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-ngrok-url.ngrok-free.app")

def api(method: str, **params):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/{method}", data=data)
    with urllib.request.urlopen(req) as r:
        print(json.loads(r.read()))

if not BOT_TOKEN or "PUT-YOUR" in BOT_TOKEN:
    print("Set BOT_TOKEN in backend/.env first")
else:
    api("setChatMenuButton", menu_button=json.dumps({"type": "web_app", "text": "Tasks", "web_app": {"url": WEBAPP_URL}}))
    print("Menu button set to", WEBAPP_URL)
