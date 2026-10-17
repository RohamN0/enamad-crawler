from src.crawler import EnamadCrawler
c = EnamadCrawler(['https://enamad.ir/DomainListForMIMT'], 10, 5)

info = c.get_full_info("tmdz.ir")
print(info)
