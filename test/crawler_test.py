from src.crawler import EnamadCrawler

urls = ['https://enamad.ir/DomainListForMIMT', 'https://enamad.ir/DomainListForMIMTSuspend']
enamad = EnamadCrawler(urls, page_numbers=4, time_sleep=10)

df = enamad.run()
df.to_csv('./data.csv')
