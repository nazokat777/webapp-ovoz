"""_verify_init_data uchun tez sinov — haqiqiy bot token ishlatilmaydi."""
import hmac, hashlib, json, time, urllib.parse, os, sys

os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_FOR_UNIT_CHECK"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# bot.py to'liq import qilinsa main() ishga tushmaydi (if __name__ guard bor)
import bot

TOKEN = os.environ["BOT_TOKEN"]


def build_init_data(user_id, auth_date=None, token=TOKEN, extra=None):
    auth_date = auth_date or int(time.time())
    fields = {
        "auth_date": str(auth_date),
        "query_id": "AAABBBCCC",
        "user": json.dumps({"id": user_id, "first_name": "Ali"}, separators=(",", ":")),
    }
    if extra:
        fields.update(extra)
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


ok = 0
fail = 0


def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {name}")
    else:
        fail += 1
        print(f"  FAIL  {name}")


print("_verify_init_data sinovi:")
check("to'g'ri imzo -> user_id", bot._verify_init_data(build_init_data(777)) == 777)
check("buzilgan hash -> None",
      bot._verify_init_data(build_init_data(777)[:-4] + "dead") is None)
check("boshqa token -> None",
      bot._verify_init_data(build_init_data(777, token="999:WRONG")) is None)
check("eskirgan auth_date -> None",
      bot._verify_init_data(build_init_data(777, auth_date=int(time.time()) - 90000)) is None)
check("bo'sh -> None", bot._verify_init_data("") is None)
check("None -> None", bot._verify_init_data(None) is None)
check("hash yo'q -> None", bot._verify_init_data("user=%7B%22id%22%3A1%7D&auth_date=1") is None)
check("signature maydoni bilan ham ishlaydi",
      bot._verify_init_data(
          build_init_data(555) + "&signature=" + urllib.parse.quote("abc123==")) == 555)
check("user_id ni almashtirish urinishi -> None",
      bot._verify_init_data(
          build_init_data(777).replace(urllib.parse.quote('"id":777'),
                                       urllib.parse.quote('"id":888'))) is None)

print(f"\nNatija: {ok} pass, {fail} fail")
sys.exit(1 if fail else 0)
