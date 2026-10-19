# Enamad Crawler

Scrape the Iranian e-trust registry (`enamad.ir`) and the trust seal detail pages
(`trustseal.enamad.ir`).

## Features

* List crawl of `getDomainList` / `getSuspendDomainList` (captcha solving via ddddocr + OpenCV)
* Domain search (`s#ms-domain-address`) returning a single unified dict
* Trust seal detail page scraper (`https://trustseal.enamad.ir/?id={id}&code={code}`)
* Flask HTTP API with API-key auth (`POST /lookup`, `GET /health`)
* Disk cache + polite retries to reduce load on enamad services

## Project layout

```
enamad-crawler/
├── src/
│   ├── __init__.py
│   ├── captcha_solver.py      # ddddocr + OpenCV captcha solving
│   ├── crawler.py             # EnamadCrawler: list, search, trustseal, get_full_info
│   ├── trustseal.py           # TrustsealScraper: detail page fetch + parse + cache
│   ├── api.py                 # Flask API server
│   └── __pycache__/
├── test/                      # sample data + notebook
├── .venv/                     # local virtualenv (not committed)
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── requirements.txt
```

## Local development

```bash
# create virtualenv and install deps
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# run a domain lookup (no server)
python -c "
from src.crawler import EnamadCrawler
c = EnamadCrawler(['https://enamad.ir/DomainListForMIMT'], page_numbers=1, time_sleep=2)
print(c.get_full_info('example.ir'))
"

# run the API server
export ENAMAD_API_KEY="change-me-strong-secret"
python src/api.py
# curl -X POST http://localhost:8000/lookup \
#   -H "Authorization: Bearer change-me-strong-secret" \
#   -H "Content-Type: application/json" \
#   -d '{"domain": "example.ir"}'
```

## Run with Docker

### Build and start

```bash
docker compose up --build
```

The API listens on `http://localhost:8000`.

### Required environment variable

`ENAMAD_API_KEY` must be set, otherwise `/lookup` returns `500`.

```bash
export ENAMAD_API_KEY="change-me-strong-secret"
docker compose up --build
```

### Call the API

```bash
curl -X POST http://localhost:8000/lookup \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change-me-strong-secret" \
  -d '{"domain": "example.ir"}'

curl http://localhost:8000/health
```

### Persist the detail-page cache across restarts

The scraper caches `trustseal.enamad.ir` HTML pages in `.cache/trustseal`.
Mount a volume so the cache survives container recreation:

```yaml
# in docker-compose.yml (already included)
services:
  enamad-crawler:
    volumes:
      - enamad-cache:/app/.cache/trustseal
volumes:
  enamad-cache:
```

## API reference

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/lookup` | POST | Bearer / X-API-Key | Body: `{"domain": "example.ir", "referer_url": "...", "include_trustseal": true}` |
| `/health` | GET | none | Status check |

Response (single flat dict):

```json
{
  "found": true,
  "id": "8202379",
  "code": "I2Clbl1IEUNjkZXY1vGveS9J08jhlDGe",
  "trustseal_url": "https://trustseal.enamad.ir/?id=8202379&code=...",
  "domain": "tmdz.ir",
  "domain_url": "http://tmdz.ir/",
  "business_name": "تعاونی مسکن دادگستری زنجان",
  "owner_name": "خلیل باقری",
  "phone": "02632210564",
  "email": "noyanteam820@gmail.com",
  "address": "...",
  "support_hours": "8 الی 22",
  "issue_date": "1405/06/17",
  "expire_date": "معتبر تا تاریخ 1407/07/23",
  "business_history": "1 ماه 8 روز",
  "violations_level1": "0",
  "services": [...],
  "links": {...},
  "trustseal_ok": true,
  "error": null
}
```

## Production notes for a static-IP home server

1. **Do not expose port 8000 directly to the internet.** Put nginx (or Caddy/Traefik) with TLS in front so the API key is not sent in plaintext.
2. **Add rate limiting** at the reverse proxy (each lookup solves a captcha and fetches a detail page).
3. **Set `ENAMAD_API_KEY`** via environment, never commit it.
4. Be polite: default `time_sleep=2` and single worker. Increase the delay if you crawl many domains.
5. Persist `.cache/trustseal` so repeat lookups don't re-hit enamad.

## Legal / ethical reminder

Only scrape data you are authorized to access. Respect `enamad.ir` terms of service, robots.txt, and applicable law. This tool is for study and legitimate personal use on your own infrastructure.
