from datetime import datetime, timedelta
from src.captcha_solver import CaptchaSolver
from urllib.parse import urlparse
import pandas as pd
import requests, time
import base64, os
import jdatetime

class EnamadCrawler:
    def __init__(self, urls, page_numbers, time_sleep, db_path=None):
        self.urls = urls
        self.page_numbers = page_numbers
        self.time_sleep = time_sleep
        self.db_path = db_path
        self.captcha_url = "https://enamad.ir/refreshCapt"
        
        self.api_url_mapping = {
            "https://enamad.ir/DomainListForMIMT": "https://enamad.ir/getDomainList",
            "https://enamad.ir/DomainListForMIMTSuspend": "https://enamad.ir/getSuspendDomainList"
        }
        
        self.columns = ['type', 'domain_address', 'persian_name', 'province', 
                        'city', 'rating', 'approve_date', 'expire_date', 'is_expiration_close']

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

    def get_domains_list(self, referer_url):
        api_url = self.api_url_mapping.get(referer_url)
        if not api_url: return []
            
        session = requests.Session()
        self.headers["Referer"] = referer_url
        session.get(referer_url, headers=self.headers)
        
        all_domains = []
        solver = CaptchaSolver()
        
        for page_idx in range(self.page_numbers):
            img_bytes, token = self._refresh_captcha(session)
            if not img_bytes: break

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
                if not items: break
                all_domains.extend(items)
            except Exception:
                break
            time.sleep(self.time_sleep)
            
        return all_domains

    def run(self):
        new_frames = []
        for url in self.urls:
            raw_data = self.get_domains_list(url)
            if not raw_data: continue
                
            df = pd.DataFrame(raw_data)
            path = urlparse(url).path
            df['type'] = path.strip('/').split('/')[-1]
            
            for col in self.columns:
                if col not in df.columns: df[col] = None
            
            new_frames.append(df[self.columns])

        if self.db_path and os.path.exists(self.db_path):
            existing_df = pd.read_csv(self.db_path)
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
