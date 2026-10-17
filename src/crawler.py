from datetime import datetime, timedelta
from src.captcha_solver import CaptchaSolver
from urllib.parse import urlparse
import pandas as pd
import requests, time
import base64, os
import jdatetime

class EnamadCrawler:
    def __init__(self, urls, page_numbers, time_sleep, db_path=None, max_captcha_attempts=3):
        self.urls = urls
        self.page_numbers = page_numbers
        self.time_sleep = time_sleep
        self.db_path = db_path
        self.max_captcha_attempts = max_captcha_attempts
        self.captcha_url = "https://enamad.ir/refreshCapt"
        
        self.api_url_mapping = {
            "https://enamad.ir/DomainListForMIMT": "https://enamad.ir/getDomainList",
            "https://enamad.ir/DomainListForMIMTSuspend": "https://enamad.ir/getSuspendDomainList"
        }
        
        self.columns = ['id', 'code', 'type', 'domain_address', 'persian_name', 'province',
                        'city', 'rating', 'approve_date', 'expire_date', 'is_expiration_close']

        # Raw API sometimes uses different casing/names for the same fields.
        self.column_aliases = {
            "id": ["id", "applicant_id", "applicantid", "domain_id", "row_id", "ID", "Id"],
            "code": ["code", "enamad_code", "enamadcode", "symbol_code", "namad_code", "Code"],
        }

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": 'https://enamad.ir',
        }

    def _get_payload_template(self):
        return {
            "s#ms-domain-address": "", "s#ms-persian-name": "", "s#ms-product-service-id-enc": "",
            "s#mi-rating": "-1", "s#ms-province-id-enc": "", "s#ms-city-id-enc": "",
            "Capt": "", "Csearch": "", "page": "0", "token": "", "cptToken": "", "checkcapga": "1"
        }

    def _refresh_captcha(self, session):
        try:
            response = session.post(self.captcha_url, headers=self.headers, timeout=10)
            res_json = response.json()
            encoded_data = res_json['captha'].split(",")[-1]
            return base64.b64decode(encoded_data), res_json['cptToken']
        except Exception:
            return None, None

    def _jalali_to_gregorian(self, jalali_str):
        if not jalali_str or pd.isna(jalali_str) or str(jalali_str).strip() == "":
            return None
        try:
            clean_str = str(jalali_str).strip().replace('-', '/')
            j_date = jdatetime.datetime.strptime(clean_str, '%Y/%m/%d')
            return j_date.togregorian()
        except (ValueError, TypeError):
            return None

    def _compute_expiration_close(self, df):
        if df.empty:
            return df
            
        now_gregorian = datetime.now()
        one_month_from_now = now_gregorian + timedelta(days=30)

        gregorian_expires = df['expire_date'].apply(self._jalali_to_gregorian)
        
        df['is_expiration_close'] = gregorian_expires.apply(
            lambda x: x is not None and x <= one_month_from_now
        )
        
        return df

    def _normalize_domain(self, domain_address):
        if not domain_address:
            return ""
        d = str(domain_address).strip().lower()
        for prefix in ("https://", "http://"):
            if d.startswith(prefix):
                d = d[len(prefix):]
        d = d.split("/")[0].split("?")[0].split("#")[0]
        d = d.split(":")[0]
        if d.startswith("www."):
            d = d[4:]
        return d.strip()

    def _ensure_id_code(self, df):
        lower_map = {str(c).strip().lower(): c for c in df.columns}
        for target, aliases in self.column_aliases.items():
            if target in df.columns:
                continue
            for alias in aliases:
                key = alias.strip().lower()
                if key in lower_map:
                    df[target] = df[lower_map[key]]
                    break
        return df

    def _to_frame(self, raw_data, referer_url):
        if not raw_data:
            return pd.DataFrame(columns=self.columns)
        df = pd.DataFrame(raw_data)
        df = self._ensure_id_code(df)
        path = urlparse(referer_url).path
        df['type'] = path.strip('/').split('/')[-1]
        for col in self.columns:
            if col not in df.columns:
                df[col] = None
        df = df[self.columns]
        return self._compute_expiration_close(df)

    def search_domain(self, domain_address, referer_url=None):
        domain = self._normalize_domain(domain_address)
        if not domain:
            return pd.DataFrame(columns=self.columns)

        if referer_url is None:
            if not self.urls:
                return pd.DataFrame(columns=self.columns)
            referer_url = self.urls[0]

        api_url = self.api_url_mapping.get(referer_url)
        if not api_url:
            return pd.DataFrame(columns=self.columns)

        session = requests.Session()
        self.headers["Referer"] = referer_url
        session.get(referer_url, headers=self.headers)

        solver = CaptchaSolver()
        for _ in range(self.max_captcha_attempts):
            img_bytes, token = self._refresh_captcha(session)
            if not img_bytes:
                break

            payload = self._get_payload_template()
            payload.update({
                "s#ms-domain-address": domain,
                "Capt": solver.solve(img_bytes),
                "cptToken": token,
                "token": token,
                "page": "0",
                "checkcapga": "1",
            })

            try:
                res = session.post(api_url, headers=self.headers, data=payload, timeout=15)
                items = res.json().get('applicantDomainsList', [])
                if items:
                    return self._to_frame(items, referer_url)
            except Exception:
                pass

            time.sleep(self.time_sleep)

        return pd.DataFrame(columns=self.columns)

    def get_trustseal(self, id, code, timeout=15):
        """Fetch + parse one trustseal detail page. Returns dict with ok/fields/url."""
        from src.trustseal import TrustsealScraper
        return TrustsealScraper(timeout=timeout, delay=0).scrape(id, code)

    def enrich_with_trustseal(self, df, delay=1.0, timeout=15):
        """Add ts_* detail columns for every (id, code) row in df. Returns new DataFrame."""
        from src.trustseal import TrustsealScraper
        return TrustsealScraper(timeout=timeout, delay=delay).enrich_df(df, delay=delay)

    def get_full_info(self, domain_address=None, id=None, code=None, referer_url=None,
                      include_trustseal=True, timeout=15):
        """Single unified dict for one business, with proper English keys.

        Lookup by domain (list API) or directly by id+code. Merges list row
        with trustseal detail page. Never raises; missing values are None.
        """
        from src.trustseal import build_url

        def _val(v):
            try:
                import pandas as pd
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return None
                if pd.isna(v):
                    return None
            except Exception:
                pass
            try:
                import numpy as np
                if isinstance(v, np.generic):
                    return v.item()
            except Exception:
                pass
            if isinstance(v, str):
                v = v.strip()
                return v if v not in ("", "nan", "None", "NaN") else None
            return v

        out = {
            "query": _val(domain_address) or (f"id={id}&code={code}" if id and code else None),
            "found": False,
            "id": _val(id),
            "code": _val(code),
            "trustseal_url": None,
            "domain": _val(domain_address and self._normalize_domain(domain_address)),
            "shop_name": None,
            "business_name": None,
            "persian_name": None,
            "owner_name": None,
            "province": None,
            "city": None,
            "address": None,
            "postal_code": None,
            "phone": None,
            "email": None,
            "domain_url": None,
            "support_hours": None,
            "business_history": None,
            "violations_level1": None,
            "violations_level2": None,
            "violations_level3": None,
            "violations_level4": None,
            "services": [],
            "type": None,
            "symbol_type": None,
            "rating": None,
            "status": None,
            "approve_date": None,
            "issue_date": None,
            "expire_date": None,
            "is_expiration_close": None,
            "trustseal_ok": None,
            "trustseal_error": None,
            "links": {},
            "error": None,
        }

        # 1. List lookup (gives id/code + base row) when domain given
        raw_list = None
        if domain_address:
            try:
                df = self.search_domain(domain_address, referer_url=referer_url)
            except Exception as e:
                out["error"] = f"search: {e}"
                df = None
            if df is not None and not df.empty:
                norm = self._normalize_domain(domain_address)
                row = None
                try:
                    exact = df[df["domain_address"].astype(str).str.lower().str.strip() == norm]
                    row = exact.iloc[0] if not exact.empty else df.iloc[0]
                except Exception:
                    row = df.iloc[0]
                raw_list = {k: _val(row.get(k)) for k in self.columns if k in row.index}
                out["found"] = True
                out["id"] = raw_list.get("id") or out["id"]
                out["code"] = raw_list.get("code") or out["code"]
                out["domain"] = raw_list.get("domain_address") or out["domain"]
                out["persian_name"] = raw_list.get("persian_name")
                out["province"] = raw_list.get("province")
                out["city"] = raw_list.get("city")
                out["type"] = raw_list.get("type")
                out["approve_date"] = raw_list.get("approve_date")
                out["expire_date"] = raw_list.get("expire_date")
                out["is_expiration_close"] = raw_list.get("is_expiration_close")
                try:
                    r = raw_list.get("rating")
                    out["rating"] = int(r) if r is not None else None
                except Exception:
                    out["rating"] = raw_list.get("rating")
        elif id and code:
            out["found"] = True  # direct mode, no list search

        if out["id"] and out["code"]:
            try:
                out["trustseal_url"] = build_url(out["id"], out["code"])
            except Exception:
                pass

        # 2. Trustseal detail page (authoritative for contact/address/dates)
        if include_trustseal and out["id"] and out["code"]:
            try:
                ts = self.get_trustseal(out["id"], out["code"], timeout=timeout)
            except Exception as e:
                ts = {"ok": False, "error": str(e), "fields": {}, "links": {}}
            out["trustseal_ok"] = bool(ts.get("ok"))
            out["trustseal_error"] = ts.get("error")
            out["links"] = ts.get("links", {}) or {}
            out["services"] = ts.get("services", []) or []
            fields = ts.get("fields", {}) or {}
            for k in ("shop_name", "business_name", "name", "domain", "domain_url", "symbol_type",
                      "issue_date", "expire_date", "status", "address", "phone", "email",
                      "owner_name", "city", "province", "postal_code", "support_hours", "rating",
                      "business_history", "violations_level1", "violations_level2",
                      "violations_level3", "violations_level4"):
                v = _val(fields.get(k))
                if v is None:
                    continue
                if k == "name" and not out["shop_name"]:
                    out["shop_name"] = v
                elif k == "domain" and v:
                    out["domain"] = v
                elif k in ("city", "province", "expire_date", "rating", "phone", "email",
                           "address", "owner_name", "status", "symbol_type", "issue_date",
                           "postal_code", "support_hours", "shop_name", "business_name",
                           "domain_url", "business_history", "violations_level1",
                           "violations_level2", "violations_level3", "violations_level4"):
                    # detail page wins when present
                    if k == "rating":
                        try:
                            out[k] = int(v)
                        except Exception:
                            out[k] = v
                    else:
                        out[k] = v
            if not out["found"] and out["trustseal_ok"]:
                out["found"] = True
            if raw_list is None and not domain_address and id and code:
                out["found"] = bool(out["trustseal_ok"])
                if not out["found"]:
                    out["error"] = out["trustseal_error"]
            if out["trustseal_ok"] is False and not raw_list and not (id and code and domain_address):
                out["error"] = out["trustseal_error"]
        elif include_trustseal and not (out["id"] and out["code"]):
            out["trustseal_ok"] = False
            out["trustseal_error"] = out.get("error") or "not found in list; id/code unknown"
            if not out["found"]:
                out["error"] = out["error"] or "domain not found"

        # keep raw for debugging without polluting proper keys
        if raw_list is not None:
            out["_raw_list"] = raw_list
        return out

    # Alias: shorter name
    def lookup(self, *args, **kwargs):
        return self.get_full_info(*args, **kwargs)

    def get_domains_list(self, referer_url):
        api_url = self.api_url_mapping.get(referer_url)
        if not api_url: return []
            
        session = requests.Session()
        self.headers["Referer"] = referer_url
        session.get(referer_url, headers=self.headers)
        
        all_domains = []
        solver = CaptchaSolver()
        
        for page_idx in range(0, self.page_numbers + 1):
            if page_idx == 1 : continue

            page_success = False
            for attempt in range(self.max_captcha_attempts):
                img_bytes, token = self._refresh_captcha(session)
                if not img_bytes:
                    break

                payload = self._get_payload_template()
                payload.update({
                    "Capt": solver.solve(img_bytes),
                    "cptToken": token,
                    "token": token,
                    "page": str(page_idx),
                    "checkcapga": "1" if page_idx == 0 else "0"
                })

                try:
                    res = session.post(api_url, headers=self.headers, data=payload, timeout=15)
                    items = res.json().get('applicantDomainsList', [])
                    if items:
                        all_domains.extend(items)
                        page_success = True
                        print(page_idx)
                        break
                except Exception:
                    pass

                time.sleep(self.time_sleep)

            if not page_success:
                break
            time.sleep(self.time_sleep)
            
        return all_domains

    def run(self):
        new_frames = []
        for url in self.urls:
            raw_data = self.get_domains_list(url)
            if not raw_data: continue
                
            df = pd.DataFrame(raw_data)
            df = self._ensure_id_code(df)
            path = urlparse(url).path
            df['type'] = path.strip('/').split('/')[-1]
            
            for col in self.columns:
                if col not in df.columns: df[col] = None
            
            new_frames.append(df[self.columns])

        if self.db_path and os.path.exists(self.db_path):
            existing_df = pd.read_csv(self.db_path, index_col=0)
            if new_frames:
                combined_df = pd.concat([existing_df] + new_frames, ignore_index=True)
            else:
                combined_df = existing_df
        else:
            combined_df = pd.concat(new_frames, ignore_index=True) if new_frames else pd.DataFrame(columns=self.columns)

        if not combined_df.empty and 'domain_address' in combined_df.columns:
            combined_df = combined_df.drop_duplicates(subset=['domain_address'], keep='last')

        combined_df = self._compute_expiration_close(combined_df)
        
        if self.db_path:
            combined_df.to_csv(self.db_path, index=False)
            
        return combined_df
