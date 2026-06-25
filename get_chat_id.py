"""Print your Telegram chat id for login notifications.

Steps:
  1. In Telegram, message @BotFather -> /newbot -> copy the bot token.
  2. Send your new bot any message (e.g. "hi") so it has a chat to read.
  3. Run:  .venv\\Scripts\\python.exe get_chat_id.py <BOT_TOKEN>

Then put the token + printed chat id into secrets.local.ps1 (RD_TELEGRAM_*).
"""
import sys
import json
import urllib.request

tok = (sys.argv[1] if len(sys.argv) > 1 else input("Bot token: ")).strip()
url = "https://api.telegram.org/bot%s/getUpdates" % tok
data = json.load(urllib.request.urlopen(url, timeout=10))

seen = {}
for u in data.get("result", []):
    msg = u.get("message") or u.get("edited_message") or {}
    chat = msg.get("chat", {})
    if chat.get("id") is not None:
        seen[chat["id"]] = chat.get("username") or chat.get("first_name", "")

if seen:
    for cid, name in seen.items():
        print("chat_id: %s   (%s)" % (cid, name))
else:
    print("No messages found. Send your bot a message first, then re-run this.")
