from src.crawler import EnamadCrawler

urls = ['https://enamad.ir/DomainListForMIMT', 'https://enamad.ir/DomainListForMIMTSuspend']
# New csv
# enamad = EnamadCrawler(urls, page_numbers=2, time_sleep=10)
# df = enamad.run()
# df.to_csv('./test/data.csv')

# DB
enamad = EnamadCrawler(urls, page_numbers=2, time_sleep=10, db_path='./test/data.csv')
df = enamad.run()
