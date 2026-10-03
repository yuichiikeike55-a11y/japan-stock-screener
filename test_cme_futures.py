import yfinance as yf


def main():
    ticker = "NKD=F"

    print("=== CME Nikkei 225 Futures Test ===")
    print("Ticker:", ticker)

    data = yf.download(
        ticker,
        period="5d",
        interval="1d",
        progress=False,
        auto_adjust=False,
    )

    print()
    print("Rows:", len(data))
    print("Columns:", list(data.columns))
    print()
    print(data.tail())

    if data.empty:
        raise RuntimeError(
            f"{ticker}: yfinance returned no data"
        )

    print()
    print("SUCCESS:", ticker)


if __name__ == "__main__":
    main()
