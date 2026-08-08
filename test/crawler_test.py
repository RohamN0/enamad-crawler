from src.crawler import EnamadCrawler

urls = ['https://enamad.ir/DomainListForMIMT', 'https://enamad.ir/DomainListForMIMTSuspend']
# New csv
# enamad = EnamadCrawler(urls, page_numbers=4, time_sleep=10, db_path=None)

# DB
enamad = EnamadCrawler(urls, page_numbers=4, time_sleep=10, db_path='./test/data.csv')

df = enamad.run()
df.to_csv('./test/data.csv')
