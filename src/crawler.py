from captcha_solver import CaptchaSolver
from urllib.parse import urlparse
import pandas as pd
import requests, base64, json, time

class EnamadCrawler:
    def __init__(self, urls, page_numbers, time_sleep):
        self.urls = urls
        self.page_numbers = page_numbers
        self.time_sleep = time_sleep
        self.captcha_url = "https://enamad.ir/refreshCapt"
        
        self.api_url_mapping = {
            "https://enamad.ir/DomainListForMIMT": "https://enamad.ir/getDomainList",
            "https://enamad.ir/DomainListForMIMTSuspend": "https://enamad.ir/getSuspendDomainList"
        }
        
        self.columns = ['type', 'domain_address', 'persian_name', 'province', 
                        'city', 'rating', 'approve_date', 'expire_date']

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:153.0) Gecko/20100101 Firefox/153.0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": 'https://enamad.ir',
            "Connection": "keep-alive",
            "Referer": "",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        self.data = {
            "s#ms-domain-address": "",
            "s#ms-persian-name": "",
            "s#ms-product-service-id-enc": "",
            "s#mi-rating": "-1",
            "s#ms-province-id-enc": "",
            "s#ms-city-id-enc": "",
            "Capt": "",
            "Csearch": "",
            "page": "0",
            "token": "",
            "cptToken": "",
            "checkcapga": "1"
        }

    def __create_session(self, referer_url):
        session = requests.Session()
        self.headers["Referer"] = referer_url
        session.get(referer_url, headers=self.headers)
        return session

    def _refresh_captcha(self, session):
        response = session.post(self.captcha_url, headers=self.headers, verify=True)
        response = json.loads(response.text)
        data_uri = 'data:image/jpeg;base64,' + response['captha']
        _, encoded_data = data_uri.split(",", 1)
        image_bytes = base64.b64decode(encoded_data)
        return image_bytes, response['cptToken']

    def _solve_captcha(self, image):
        captcha = CaptchaSolver()
        return captcha.solve(image)

    def get_domains_list(self, referer_url):
        api_url = self.api_url_mapping.get(referer_url)
        if not api_url:
            raise ValueError(f"No API URL mapping found for {referer_url}")
            
        domains_list = []
        session = self.__create_session(referer_url)
        
        self.data = {
            "s#ms-domain-address": "",
            "s#ms-persian-name": "",
            "s#ms-product-service-id-enc": "",
            "s#mi-rating": "-1",
            "s#ms-province-id-enc": "",
            "s#ms-city-id-enc": "",
            "Capt": "",
            "Csearch": "",
            "page": "0",
            "token": "",
            "cptToken": "",
            "checkcapga": "1"
        }

        for i in range(self.page_numbers + 1):
            image_bytes, token = self._refresh_captcha(session)

            self.data['Capt'] = self._solve_captcha(image_bytes)
            self.data['cptToken'] = token
            self.data['token'] = token

            if i == 0:
                first_page_res = session.post(
                    api_url, headers=self.headers, data=self.data).json()
                domains_list.extend(first_page_res.get('applicantDomainsList', []))
            elif i == 1:
                continue
            else:
                self.data['checkcapga'] = "0"
                self.data['page'] = str(i)
                res = session.post(
                    api_url, headers=self.headers, data=self.data).json()
                domains_list.extend(res.get('applicantDomainsList', []))

            time.sleep(self.time_sleep)

        return domains_list

    def domains_list_to_csv(self, referer_url):
        domains_list = self.get_domains_list(referer_url)
        
        if not domains_list:
            return pd.DataFrame(columns=self.columns)
            
        domains_df = pd.DataFrame(domains_list)
        
        path = urlparse(referer_url).path
        domain_type = path.strip('/').split('/')[-1] if path else "unknown"
        
        domains_df['type'] = domain_type

        for col in self.columns:
            if col not in domains_df.columns:
                domains_df[col] = None
        domains_df = domains_df[self.columns]
        return domains_df

    def run(self):
        frames = []
        for url in self.urls:
            df = self.domains_list_to_csv(url)
            frames.append(df)
        if not frames:
            return pd.DataFrame(columns=self.columns)
        return pd.concat(frames, ignore_index=True)