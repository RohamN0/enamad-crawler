"""Scrape business detail pages: https://trustseal.enamad.ir/?id={id}&code={code}"""
from urllib.parse import urlencode
import re
import time

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None


BASE_URL = "https://trustseal.enamad.ir/"

# trustseal.ir returns 500 without a browser-like Referer (verified).
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:154.0) Gecko/20100101 Firefox/154.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
    "Referer": "https://enamad.ir/",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-site",
}

# Persian label -> normalized english key. Original Persian key is always kept too.
LABEL_MAP = {
    "نام فروشگاه": "shop_name",
    "نام کسب و کار": "business_name",
    "کسب و کار": "business_name",
    "نام": "name",
    "آدرس دامنه": "domain",
    "دامنه": "domain",
    "نوع نماد": "symbol_type",
    "نوع نماد اعتماد": "symbol_type",
    "تاریخ صدور": "issue_date",
    "تاریخ اعطا": "issue_date",
    "تاریخ اعتبار": "expire_date",
    "تاریخ انقضا": "expire_date",
    "تاریخ انتقضا": "expire_date",
    "اعتبار": "expire_date",
    "وضعیت": "status",
    "وضعیت نماد": "status",
    "وضعیت اینماد": "status",
    "آدرس": "address",
    "نشانی": "address",
    "تلفن": "phone",
    "تلفن تماس": "phone",
    "شماره تماس": "phone",
    "شماره های مرکز تماس": "support_phone",
    "پست الکترونیک": "email",
    "پست الکترونیکی": "email",
    "ایمیل": "email",
    "رایانامه": "email",
    "نام صاحب امتیاز": "owner_name",
    "صاحب امتیاز": "owner_name",
    "شناسه": "id",
    "کد": "code",
    "شهر": "city",
    "استان": "province",
    "کد پستی": "postal_code",
    "ساعت پاسخگویی": "support_hours",
    "رتبه": "rating",
    "ستاره": "rating",
    "سابقه کسب و کار": "business_history",
    "تعداد شکایات پاسخ داده نشده": "unanswered_complaints",
    "تعداد تاخیر در پاسخ دهی": "late_responses",
    "سطح چهار": "violations_level4",
    "سطح سوم": "violations_level3",
    "سطح دوم": "violations_level2",
    "سطح اول": "violations_level1",
}


def build_url(id, code):
    return f"{BASE_URL}?{urlencode({'id': str(id), 'code': str(code)})}"


def _clean(s):
    if s is None:
        return ""
    s = s.replace("\xa0", " ").replace("\u200c", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm_label(s):
    """Normalize Persian/Arabic variants so 'پست الكترونیكی:' matches LABEL_MAP."""
    s = _clean(s).replace(":", "").replace("：", "")
    s = s.replace("ي", "ی").replace("ك", "ک").replace("‌", " ").replace("  ", " ")
    return _clean(s)


def _deobfuscate(s):
    if not isinstance(s, str):
        return s
    s = re.sub(r"\s*\[at\]\s*", "@", s, flags=re.I)
    s = re.sub(r"\s*\(at\)\s*", "@", s, flags=re.I)
    return s.strip()


def _is_error_page(soup, html):
    title = _clean(soup.title.get_text()) if soup.title else ""
    if "خطا" in title:
        # Error template has no business tables, only nav buttons.
        if not soup.find("table"):
            return True
    # Fallback: explicit error markers with no data pairs
    if "بازگشت به سایت نماد" in html and "نماد تجارت الکترونیکی" in title:
        return True
    return False


def _extract_pairs(soup):
    """Extract label->value pairs from tables, dl, sibling-row divs, colon blocks."""
    pairs = {}

    def _put(k, v):
        k, v = _clean(k), _clean(_deobfuscate(v))
        if k and v and len(k) < 80 and len(v) < 500:
            # drop container garbage: key looks like a sentence/domain, or
            # value is actually the next label (ends with ':') or footer junk
            if "." in k or "/" in k or len(k.split()) > 5:
                return
            if v.endswith(":") or "جهت مشاهده اطلاعات تکمیلی" in v:
                return
            pairs.setdefault(k, v)

    # 0. Main trustseal pattern: <div class="row"><div>label</div><div>value</div></div>
    for row in soup.select("div.row"):
        cols = row.find_all("div", recursive=False)
        if len(cols) == 2:
            k = _clean(cols[0].get_text(separator=" "))
            v = _clean(cols[1].get_text(separator=" "))
            if k and v and len(k) < 60 and "col-" in str(cols[0].get("class", "")):
                _put(k.rstrip(":："), v)

    # 1. tables: label/value only (skip header rows + services table)
    for table in soup.find_all("table"):
        if "عنوان خدمت" in table.get_text():
            continue
        for tr in table.find_all("tr"):
            if tr.find("th"):
                continue
            cells = tr.find_all(["th", "td"])
            if len(cells) >= 2:
                _put(_clean(cells[0].get_text(separator=" ")),
                     _clean(cells[1].get_text(separator=" ")))
            elif len(cells) == 1:
                # single cell like "نام فروشگاه : value"
                txt = _clean(cells[0].get_text(separator=" "))
                if ":" in txt or "：" in txt:
                    k, v = re.split(r"[:：]", txt, maxsplit=1)
                    if k.strip() and v.strip():
                        _put(k.strip(), v.strip())

    # 2. definition lists
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            _put(dt.get_text(" "), dd.get_text(" "))

    # 3. generic label/value divs: class hints or colon text
    for tag in soup.find_all(["div", "li", "p", "span"]):
        # skip containers with nested block pairs already handled
        if tag.find("table") or tag.find("dl"):
            continue
        txt = _clean(tag.get_text(separator=" "))
        if not txt or len(txt) > 300:
            continue
        if ":" in txt or "：" in txt:
            k, v = re.split(r"[:：]", txt, maxsplit=1)
            k, v = k.strip(), v.strip()
            # label should be short Persian text, value non-empty
            if 1 < len(k) < 60 and v and tag.find(["a", "span", "strong", "label", "b"]):
                _put(k, v)

    # 4. explicit label elements followed by sibling value
    for label in soup.find_all(["label", "span", "strong", "b"]):
        k = _clean(label.get_text())
        if not k or len(k) > 60 or ":" in k:
            continue
        parent = label.parent
        if parent is None:
            continue
        full = _clean(parent.get_text(separator=" "))
        # "label: value" or "label value"
        if full.startswith(k):
            v = full[len(k):].lstrip(":：- ").strip()
            if v and len(v) < 300:
                _put(k.rstrip(":："), v)
    return pairs


def _extract_structured(soup):
    """Business header, domain link, violation levels, services table."""
    extra = {}
    # Business name from "شناسنامه کسب و کار 'NAME'"
    for h in soup.find_all(["h1", "h2", "h3", "h4"]):
        t = _clean(h.get_text(separator=" "))
        m = re.search(r"شناسنامه کسب و کار\s*['\"«»'\u2018\u2019](.+?)['\"«»'\u2018\u2019]", t)
        if m and len(m.group(1)) > 1:
            extra["business_name"] = m.group(1).strip()
            break
    # Domain link
    a = soup.select_one("a.domainlink")
    if a:
        extra["domain"] = _clean(a.get_text())
        if a.get("href"):
            extra["domain_url"] = a["href"].strip()
    # Violation levels + complaint stats live as sibling rows; regex on text
    text = soup.get_text(separator=" ")
    for lvl, key in [("چهار", "violations_level4"), ("سوم", "violations_level3"),
                     ("دوم", "violations_level2"), ("اول", "violations_level1")]:
        m = re.search(rf"سطح\s*{lvl}\s*:\s*(\d+)", text)
        if m:
            extra[key] = m.group(1)
    for pat, key in [(r"تعداد شکایات پاسخ داده نشده\s*:\s*(\d+)", "unanswered_complaints"),
                     (r"تعداد تاخیر در پاسخ دهی\s*:\s*(\d+)", "late_responses"),
                     (r"سابقه کسب و کار\s*:\s*(.+?)(?:اطلاعات تماس|خدمات|$)", "business_history")]:
        m = re.search(pat, text, re.S)
        if m:
            extra[key] = _clean(m.group(1))[:200]
    # Services table (has عنوان خدمت header)
    services = []
    for table in soup.find_all("table"):
        headers = [_clean(c.get_text()) for c in table.find_all("th")]
        if "عنوان خدمت" in " ".join(headers):
            for tr in table.find_all("tr")[1:]:
                tds = [_clean(c.get_text()) for c in tr.find_all("td")]
                if tds and any(tds):
                    services.append(dict(zip(headers or [f"col{i}" for i in range(len(tds))], tds)))
            if services:
                extra["services"] = services
            break
    return extra


def parse(html):
    """Parse trustseal HTML -> dict. Never raises on layout changes."""
    if BeautifulSoup is None:
        raise ImportError("beautifulsoup4 is required: pip install beautifulsoup4")
    soup = BeautifulSoup(html, "html.parser")
    if _is_error_page(soup, html):
        return {"ok": False, "error": "invalid id/code or expired symbol (error page)", "fields": {}}

    pairs = _extract_pairs(soup)
    structured = _extract_structured(soup)

    # hyperlinks of interest (domain link, complaint link)
    links = {}
    for a in soup.find_all("a", href=True):
        txt = _clean(a.get_text())
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "#")):
            continue
        if len(txt) < 60 and txt:
            links.setdefault(txt, href)

    # regex fallbacks for contact info anywhere on page
    text = _deobfuscate(soup.get_text(separator=" "))
    emails = sorted(set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)))
    # Iranian phones: 021-..., 09..., +98...
    phones = sorted(set(re.findall(r"(?:\+98|0)?9\d{9}|0\d{2,3}[- ]?\d{3,4}[- ]?\d{4}", text)))

    fields = dict(pairs)  # original Persian keys preserved
    fields.update({k: v for k, v in structured.items() if k != "services"})
    # normalized English keys via Persian label map (arabic-variant aware)
    norm_pairs = {_norm_label(k): v for k, v in pairs.items()}
    for fa, en in LABEL_MAP.items():
        if en not in fields or not fields[en]:
            v = norm_pairs.get(_norm_label(fa))
            if v:
                fields[en] = _deobfuscate(v)
    for k, v in structured.items():
        if k != "services" and (k not in fields or not fields[k]):
            fields[k] = v

    # drop footer junk mislabeled as status (long modal text)
    if isinstance(fields.get("status"), str) and len(fields["status"]) > 60:
        fields.pop("status", None)
    # drop composite/container pairs; structured values already cover these
    for bad in ("سطح چهار", "آدرس آدرس", "1", "#"):
        v = fields.get(bad)
        if isinstance(v, str) and ("سطح سوم" in v or bad in ("آدرس آدرس", "1", "#")):
            fields.pop(bad, None)
    # drop complaint counts that captured the next label instead of digits
    for ck in ("unanswered_complaints", "late_responses"):
        v = fields.get(ck)
        if isinstance(v, str) and not re.fullmatch(r"\d+", v.strip()):
            fields.pop(ck, None)

    if emails and "email" not in fields:
        fields["email"] = emails[0]
    if phones and "phone" not in fields:
        fields["phone"] = ", ".join(phones[:3])
    if emails:
        fields["_all_emails"] = emails
    if phones:
        fields["_all_phones"] = phones

    title = _clean(soup.title.get_text()) if soup.title else ""
    out = {"ok": True, "title": title, "fields": fields, "links": links}
    if structured.get("services"):
        out["services"] = structured["services"]
    return out


class TrustsealScraper:
    """Polite single-identity scraper with disk cache + retries.

    No UA/proxy rotation by design — use cache, delay, and backoff
    to reduce load instead of evading blocks.
    """

    def __init__(self, timeout=15, delay=1.0, session=None, cache_dir=".cache/trustseal",
                 cache_ttl=7 * 24 * 3600, max_retries=3, user_agent=None):
        from pathlib import Path
        self.timeout = timeout
        self.delay = delay
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        headers = dict(HEADERS)
        if user_agent:  # single honest identity, not a rotation pool
            headers["User-Agent"] = user_agent
        self.session.headers.update(headers)

    def _cache_path(self, id, code):
        if not self.cache_dir:
            return None
        safe_code = re.sub(r"[^A-Za-z0-9_-]", "_", str(code))[:64]
        return self.cache_dir / f"{str(id).strip()}_{safe_code}.html"

    def _read_cache(self, id, code):
        import time as _time
        p = self._cache_path(id, code)
        if not p or not p.exists():
            return None
        try:
            if self.cache_ttl and (_time.time() - p.stat().st_mtime) > self.cache_ttl:
                return None
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

    def _write_cache(self, id, code, html):
        p = self._cache_path(id, code)
        if not p:
            return
        try:
            p.write_text(html, encoding="utf-8")
        except Exception:
            pass

    def fetch(self, id, code):
        """Returns (html, url, status, cached). Retries 429/5xx with backoff."""
        import random
        url = build_url(id, code)
        cached_html = self._read_cache(id, code)
        if cached_html is not None:
            return cached_html, url, 200, True
        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                r = self.session.get(url, timeout=self.timeout)
                if r.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep((2 ** attempt) + random.uniform(0, 1))
                    continue
                # cache only successful business pages, not error template
                if r.status_code == 200 and "بازگشت به سایت نماد" not in r.text[:5000]:
                    self._write_cache(id, code, r.text)
                elif r.status_code == 200:
                    # error page: don't cache, caller gets ok=False
                    pass
                return r.text, r.url, r.status_code, False
            except requests.RequestException as e:
                last_exc = e
                if attempt < self.max_retries:
                    time.sleep((2 ** attempt) + random.uniform(0, 1))
        raise last_exc if last_exc else RuntimeError("fetch failed")

    def scrape(self, id, code):
        url = build_url(id, code)
        try:
            html, final_url, status, cached = self.fetch(id, code)
        except Exception as e:
            return {"ok": False, "id": str(id), "code": str(code), "url": url, "error": str(e), "fields": {}}
        try:
            data = parse(html)
        except Exception as e:  # parser must not kill bulk runs
            return {"ok": False, "id": str(id), "code": str(code), "url": url, "error": f"parse: {e}", "fields": {}}
        data.update({"id": str(id), "code": str(code), "url": url, "final_url": final_url,
                     "status": status, "cached": cached})
        return data

    def scrape_many(self, items, delay=None):
        """items: iterable of (id, code) or {'id':..,'code':..}. Returns list of dicts."""
        import random
        delay = self.delay if delay is None else delay
        out = []
        for it in items:
            if isinstance(it, dict):
                _id, _code = it.get("id"), it.get("code")
            else:
                _id, _code = it
            if _id is None or _code is None or str(_id).strip() in ("", "nan", "None"):
                out.append({"ok": False, "id": _id, "code": _code, "error": "missing id/code", "fields": {}})
                continue
            out.append(self.scrape(_id, _code))
            if delay:
                time.sleep(delay + random.uniform(0, delay * 0.5))
        return out

    def enrich_df(self, df, id_col="id", code_col="code", delay=None):
        """Add trustseal detail columns to a DataFrame from the list crawler. Returns new DataFrame."""
        import pandas as pd

        if df.empty:
            return df.copy()
        rows = self.scrape_many(list(zip(df[id_col].tolist(), df[code_col].tolist())), delay=delay)
        detail = pd.DataFrame([
            {"_ts_ok": r.get("ok"), **{f"ts_{k}": v for k, v in r.get("fields", {}).items()}}
            for r in rows
        ])
        out = pd.concat([df.reset_index(drop=True), detail], axis=1)
        return out
