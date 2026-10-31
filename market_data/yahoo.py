"""Daily bars from Yahoo Finance through yfinance, an unofficial library."""

import re
import warnings

import pandas as pd
import yfinance as yf

# yfinance 1.7 triggers this deprecation inside its own code on pandas 3.1.
# Only this category from yfinance is hidden, so our own warnings still show.
warnings.filterwarnings("ignore", category=pd.errors.Pandas4Warning, module=r"yfinance\.")

INTERVAL = "1d"

# Most results are dropped by the name check, so ask for more than are shown.
NEWS_SEARCH_SIZE = 25
COMPANY_SUFFIXES = {"limited", "ltd", "ltd."}


def is_about_company(title, company, symbol):
    """Return True if a headline names the company or its NSE symbol.

    Yahoo's related-ticker tags cannot be trusted: articles about the Mars food company
    are tagged M&M.NS. The first two words of the name are specific enough, so
    "Tata Consultancy" does not match every Tata company. The symbol must match as a
    whole word in capitals, so TCS never matches inside another word.
    """
    words = [word for word in company.split() if word.lower() not in COMPANY_SUFFIXES]
    # "Mahindra & Mahindra": the & says nothing, and headlines often shorten the name.
    name = words[0] if len(words) > 1 and not words[1].isalpha() else " ".join(words[:2])
    return (
        name.lower() in title.lower()
        or re.search(rf"(?<!\w){re.escape(symbol)}(?!\w)", title) is not None
    )


class YahooProvider:
    name = "Yahoo (unofficial)"

    def fetch_daily(self, ticker, period):
        """Return Yahoo's daily bars for one symbol as a DataFrame.

        auto_adjust=False keeps Close as the traded close. With the default (True),
        past prices are lowered for dividends and no longer match the exchange's
        published values.

        A wrong symbol does NOT raise an exception here: yfinance returns an empty
        table, so callers must always validate what they get back.
        """
        return yf.Ticker(ticker).history(period=period, interval=INTERVAL, auto_adjust=False)

    def fetch_news(self, ticker, limit):
        """Return recent headlines that name the company, newest first as Yahoo gave them.

        Searching by ticker returns nothing for NSE stocks, so the ticker is first
        turned into a company name. An empty list means no article named the company.
        """
        quotes = yf.Search(ticker, max_results=1, news_count=0).quotes
        if not quotes:
            raise LookupError(f"Yahoo has no company name for {ticker}")
        company = quotes[0].get("longname") or quotes[0].get("shortname")
        symbol = ticker.removesuffix(".NS")

        articles = {}
        for item in yf.Search(company, max_results=1, news_count=NEWS_SEARCH_SIZE).news:
            title, link = item.get("title", ""), item.get("link", "")
            # The same press release often arrives through two wires.
            if is_about_company(title, company, symbol) and link.startswith("https://"):
                articles.setdefault(
                    title,
                    {
                        "title": title,
                        "publisher": item.get("publisher"),
                        "published_at": item.get("providerPublishTime"),
                        "link": link,
                    },
                )
        return list(articles.values())[:limit]

    def fetch_splits(self, ticker, since):
        """Return splits and bonus issues from a date on, as {ISO date: ratio}.

        This reads history() rather than the .splits property because rows with
        no splits and an empty table can be told apart: empty means the download
        failed, and an empty dict must only ever mean "no splits".
        """
        history = yf.Ticker(ticker).history(start=since, interval=INTERVAL, auto_adjust=False)
        if history.empty:
            raise ConnectionError(f"no history returned for {ticker} since {since}")
        splits = history.loc[history["Stock Splits"] != 0, "Stock Splits"]
        return {f"{day:%Y-%m-%d}": float(ratio) for day, ratio in splits.items()}
