#!/usr/bin/env python3
"""
LINE Bot → 解析房屋網址 → 存入 Notion
支援：591買賣、信義房屋、永慶房屋
"""

import os, re, time, hmac, hashlib, base64, json
import requests, httpx
from datetime import datetime
from flask import Flask, request, abort
from notion_client import Client

# ============================================================
# 設定（Railway 環境變數）
# ============================================================
LINE_CHANNEL_SECRET      = os.environ.get("LINE_CHANNEL_SECRET", "bed77883e97d785dbcaa9c44cd37ef36")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "7sjfyD73UywRFp7a7AMj72bnrjKpMEgiLnSMv0mZCVYj6UeQxrBzHJb82XN35mreMXR1AbkAHkCdefJNUttqXEC94IJsZO16/fX/wgbLodyavKxm4krK2+f9zeog3D3ttJTuAjnC3qI734gJJUOGBwdB04t89/1O/w1cDnyilFU=")
NOTION_TOKEN             = os.environ.get("NOTION_TOKEN", "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")
DATABASE_ID              = os.environ.get("DATABASE_ID", "3c1c07bb85a5459baa5c30e8fa573000")
# ============================================================

app = Flask(__name__)
notion = Client(auth=NOTION_TOKEN)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

def verify_signature(body, signature):
    hash = hmac.new(LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(hash).decode(), signature)

def reply_message(reply_token, text):
    requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}", "Content-Type": "application/json"},
        json={"replyToken": reply_token, "messages": [{"type": "text", "text": text}]}
    )

# ── 591 解析 ──────────────────────────────────────────────
def parse_591(url):
    m = re.search(r'/detail/\d+/(\d+)', url)
    if not m:
        return None, "無法取得物件ID"
    house_id = m.group(1)
    link = f"https://sale.591.com.tw/home/house/detail/2/{house_id}.html"

    s = requests.Session()
    s.headers.update({**HEADERS, "Referer": "https://sale.591.com.tw/", "Accept": "application/json"})
    resp = s.get("https://sale.591.com.tw/", timeout=10)
    csrf = resp.cookies.get("XSRF-TOKEN", "")
    if csrf:
        s.headers["X-XSRF-TOKEN"] = csrf

    # 直接打詳細 API
    r = s.get("https://bff-house.591.com.tw/v1/web/sale/detail",
              params={"id": house_id, "type": 2, "timestamp": int(time.time()*1000)}, timeout=12)
    if r.status_code == 200:
        d = r.json().get("data", {})
        info = d.get("info", d)
        if info:
            try: pw = round(float(str(info.get("price","0")).replace(",","")), 2)
            except: pw = 0.0
            if pw > 10000: pw = round(pw/10000, 2)
            try: area = round(float(str(info.get("area","0")).replace("坪","")), 3)
            except: area = 0.0
            rn = str(info.get("region_name","")).strip()
            sn = str(info.get("section_name","")).strip()
            return {
                "title": str(info.get("title","")).strip() or f"591物件#{house_id}",
                "post_id": house_id,
                "price_wan": pw,
                "unit_price": round(float(str(info.get("unitprice","0")).replace(",","")), 2) if info.get("unitprice") else 0.0,
                "area": area,
                "kind_name": str(info.get("build_purpose","")).strip(),
                "layout": str(info.get("room","")).strip(),
                "floor": str(info.get("floor","")).strip(),
                "district": rn + sn,
                "link": link, "source": "591買賣",
            }, None

    # 備用：掃列表
    for rid in [1,3,5,6,8,11]:
        for first_row in range(0, 300, 30):
            r = s.get("https://bff-house.591.com.tw/v1/web/sale/list",
                      params={"timestamp": int(time.time()*1000), "type": 2, "regionid": rid,
                              "firstRow": first_row, "shType": "list"}, timeout=12)
            if r.status_code != 200: break
            for h in r.json().get("data",{}).get("house_list",[]):
                if str(h.get("houseid","")) == house_id:
                    try: pw = round(float(str(h.get("price","0")).replace(",","")), 2)
                    except: pw = 0.0
                    if pw > 10000: pw = round(pw/10000, 2)
                    try: area = round(float(str(h.get("area","0")).replace("坪","")), 3)
                    except: area = 0.0
                    return {
                        "title": str(h.get("title","")).strip() or str(h.get("address","")).strip() or f"591物件#{house_id}",
                        "post_id": house_id,
                        "price_wan": pw, "unit_price": 0.0, "area": area,
                        "kind_name": "", "layout": str(h.get("room","")).strip(),
                        "floor": "", "district": str(h.get("region_name",""))+str(h.get("section_name","")),
                        "link": link, "source": "591買賣",
                    }, None
            time.sleep(0.2)
    return None, "找不到物件"

# ── 信義解析 ──────────────────────────────────────────────
def parse_sinyi(url):
    mid = re.search(r'/house/([A-Z0-9]+)', url)
    post_id = mid.group(1) if mid else url[-8:]
    clean_url = f"https://www.sinyi.com.tw/buy/house/{post_id}"
    s = requests.Session()
    s.headers.update({**HEADERS, "Accept": "text/html", "Referer": "https://www.sinyi.com.tw/"})
    r = s.get(clean_url, timeout=15)
    html = r.text
    title = ""
    mm = re.search(r'<title>([^<]+)</title>', html)
    if mm: title = mm.group(1).split("｜")[0].strip()
    price_wan = 0.0
    mm = re.search(r'"totalPrice"\s*:\s*(\d+)', html)
    if mm:
        try: price_wan = float(mm.group(1))
        except: pass
    unit_price = 0.0
    mm = re.search(r'"uniPrice"\s*:\s*"([\d.]+)\s*萬/坪"', html)
    if mm:
        try: unit_price = float(mm.group(1))
        except: pass
    area = 0.0
    mm = re.search(r'建物</span><span>([\d.]+)坪', html)
    if mm:
        try: area = round(float(mm.group(1)), 3)
        except: pass
    if not area and unit_price > 0 and price_wan > 0:
        area = round(price_wan / unit_price, 3)
    floor = ""
    mm = re.search(r'(\d+)樓\s*[/／]\s*(\d+)樓', html)
    if mm: floor = f"{mm.group(1)}F/{mm.group(2)}F"
    address = ""
    mm = re.search(r'"address"\s*:\s*"([^"]+)"', html)
    if mm: address = mm.group(1).strip()
    district = ""
    if address:
        am = re.search(r'(台[北中南]市|新北市|桃園市|高雄市|台南市)(\S{2,4}區)(.*)', address)
        if am: district = am.group(1) + am.group(2) + am.group(3).strip()
    layout = ""
    mm = re.search(r'(\d+房\d*廳\d*衛?)', html)
    if mm: layout = mm.group(1)
    kind_name = ""
    for k in ["電梯大樓","大樓","華廈","公寓","透天","別墅","套房"]:
        if k in html[:8000]: kind_name = k; break
    return {
        "title": title or f"信義房屋 {post_id}",
        "post_id": post_id, "price_wan": price_wan, "unit_price": unit_price,
        "area": area, "kind_name": kind_name, "layout": layout, "floor": floor,
        "district": district, "link": clean_url, "source": "信義房屋",
    }, None

# ── 永慶解析 ──────────────────────────────────────────────
def parse_yungching(url):
    mid = re.search(r'/house/(\d+)', url)
    post_id = mid.group(1) if mid else url[-8:]
    clean_url = f"https://buy.yungching.com.tw/house/{post_id}"
    s = requests.Session()
    s.headers.update({**HEADERS, "Accept": "text/html", "Referer": "https://buy.yungching.com.tw/"})
    r = s.get(clean_url, timeout=15)
    html = r.text
    title = ""
    mm = re.search(r'<title>([^<]+)</title>', html)
    if mm: title = mm.group(1).split("|")[0].strip()
    price_wan = 0.0
    mm = re.search(r'"price"\s*:\s*(\d+)\s*,\s*"priceCurrency"', html)
    if mm:
        try: price_wan = float(mm.group(1))
        except: pass
    unit_price = 0.0
    mm = re.search(r'單價\s*([\d.]+)\s*萬/坪', html)
    if mm:
        try: unit_price = float(mm.group(1))
        except: pass
    area = 0.0
    mm = re.search(r'建物坪數</h3>.*?>([\d.]+)坪', html, re.DOTALL)
    if mm:
        try: area = round(float(mm.group(1)), 3)
        except: pass
    if not area and unit_price > 0 and price_wan > 0:
        area = round(price_wan / unit_price, 3)
    floor = ""
    mm = re.search(r'class="floor">(\d+)/(\d+)樓', html)
    if mm: floor = f"{mm.group(1)}F/{mm.group(2)}F"
    district = ""
    mm = re.search(r'(台[北中南]市|新北市|桃園市|高雄市|台南市)(\S{2,4}區)(\S{2,20}(?:路|街|段|道)\S{0,6})', html[:10000])
    if mm: district = mm.group(1)+mm.group(2)+mm.group(3)
    if not district:
        mm = re.search(r'(台[北中南]市|新北市|桃園市|高雄市|台南市)(\S{2,4}區)', html[:8000])
        if mm: district = mm.group(1)+mm.group(2)
    kind_name = ""
    for k in ["整層住家","電梯大樓","大樓","華廈","公寓","透天","別墅","套房"]:
        if k in html[:8000]: kind_name = k; break
    return {
        "title": title or f"永慶房屋 {post_id}",
        "post_id": post_id, "price_wan": price_wan, "unit_price": unit_price,
        "area": area, "kind_name": kind_name, "layout": "", "floor": floor,
        "district": district, "link": clean_url, "source": "永慶房屋",
    }, None

# ── 存入 Notion ──────────────────────────────────────────
def save_to_notion(item):
    today = datetime.now().strftime("%Y-%m-%d")
    props = {
        "物件名稱":      {"title": [{"text": {"content": item.get("title","")[:200] or "（無標題）"}}]},
        "物件ID":        {"rich_text": [{"text": {"content": str(item.get("post_id",""))}}]},
        "售價（萬）":    {"number": item.get("price_wan") or None},
        "單價（萬/坪）": {"number": item.get("unit_price") or None},
        "坪數":          {"number": item.get("area") or None},
        "格局":          {"rich_text": [{"text": {"content": item.get("layout","")}}]},
        "樓層":          {"rich_text": [{"text": {"content": item.get("floor","")}}]},
        "地區":          {"rich_text": [{"text": {"content": item.get("district","")}}]},
        "591連結":       {"url": item.get("link") or None},
        "狀態":          {"select": {"name": "待確認"}},
        "蒐集日期":      {"date": {"start": today}},
    }
    if item.get("kind_name"):
        props["類型"] = {"select": {"name": item["kind_name"]}}
    notion.pages.create(parent={"database_id": DATABASE_ID}, properties=props)

# ── Flask 路由 ────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data()
    if not verify_signature(body, signature):
        abort(400)

    data = request.json
    for event in data.get("events", []):
        if event.get("type") != "message":
            continue
        if event["message"].get("type") != "text":
            continue

        reply_token = event["replyToken"]
        text = event["message"]["text"].strip()

        # 找網址
        url_match = re.search(r'https?://\S+', text)
        if not url_match:
            reply_message(reply_token, "請傳送房屋物件網址（591、信義房屋、永慶房屋）")
            continue

        url = url_match.group(0).split("?")[0]  # 去掉追蹤參數

        reply_message(reply_token, f"🔍 解析中...\n{url}")

        try:
            if "sale.591.com.tw" in url or "591.com.tw" in url:
                item, err = parse_591(url)
            elif "sinyi.com.tw" in url:
                item, err = parse_sinyi(url)
            elif "yungching.com.tw" in url:
                item, err = parse_yungching(url)
            else:
                reply_message(reply_token, "❌ 不支援此網站，目前支援：591、信義房屋、永慶房屋")
                continue

            if err or not item:
                reply_message(reply_token, f"❌ 解析失敗：{err}")
                continue

            save_to_notion(item)

            msg = (
                f"✅ 已存入 Notion！\n\n"
                f"🏠 {item.get('title','')}\n"
                f"💰 {item.get('price_wan','') or '?'}萬\n"
                f"📐 {item.get('area','') or '?'}坪\n"
                f"📍 {item.get('district','') or '?'}\n"
                f"🏢 {item.get('floor','') or '?'} {item.get('kind_name','')}\n"
                f"📋 {item.get('layout','') or '?'}"
            )
            reply_message(reply_token, msg)

        except Exception as e:
            reply_message(reply_token, f"❌ 發生錯誤：{str(e)[:100]}")

    return "OK"

@app.route("/", methods=["GET"])
def index():
    return "LINE Bot 運行中 ✅"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
