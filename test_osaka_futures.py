import re
import requests
from bs4 import BeautifulSoup


def main():
    symbol = "5040469.O"

    url = (
        "https://finance.yahoo.co.jp/quote/"
        f"{symbol}"
    )

    print("=== Osaka Nikkei 225 Futures HTTP Test ===")
    print("URL:", url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        )
    }

    import time

    response = None

    for attempt in range(1, 4):
        print(
            f"HTTP attempt: {attempt}/3"
        )

        response = requests.get(
            url,
            headers=headers,
            timeout=20,
        )

        print(
            "HTTP status:",
            response.status_code,
        )

        if response.status_code == 200:
            break

        if attempt < 3:
            print(
                "Retrying after 5 seconds..."
            )
            time.sleep(5)

    if response is None:
        raise RuntimeError(
            "No HTTP response received"
        )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    title = soup.title.get_text(
        " ",
        strip=True,
    ) if soup.title else ""

    text = soup.get_text(
        " ",
        strip=True,
    )

    print("Title:", title)
    print(
        "Symbol found:",
        symbol in text,
    )
    print(
        "Name found:",
        "日経平均先物1限月" in text,
    )

    if symbol not in text:
        raise RuntimeError(
            f"{symbol}: symbol not found in page"
        )

    if "日経平均先物1限月" not in text:
        raise RuntimeError(
            "Nikkei futures name not found in page"
        )
    # =====================================
    # Parse market data
    # =====================================

    quote_pattern = re.search(
        r"([0-9,]+\.\d+)\s+"
        r"前日比\s+"
        r"([+-]?[0-9,]+\.\d+)\s+"
        r"\(\s*([+-]?[0-9.]+)\s*%\s*\)\s+"
        r"15分ディレイ株価\s+"
        r"(\d{1,2}:\d{2})",
        text,
    )

    detail_pattern = re.search(
        r"前日終値\s+用語\s+"
        r"([0-9,]+\.\d+)\s+"
        r"\(\s*([0-9]{1,2}/[0-9]{1,2})\s*\)\s+"
        r"始値\s+用語\s+"
        r"([0-9,]+\.\d+)\s+"
        r"\(\s*\d{1,2}:\d{2}\s*\)\s+"
        r"高値\s+用語\s+"
        r"([0-9,]+\.\d+)\s+"
        r"\(\s*\d{1,2}:\d{2}\s*\)\s+"
        r"安値\s+用語\s+"
        r"([0-9,]+\.\d+)\s+"
        r"\(\s*\d{1,2}:\d{2}\s*\)\s+"
        r"出来高\s+用語\s+"
        r"([0-9,]+)\s+株",
        text,
    )

    if quote_pattern is None:
        raise RuntimeError(
            "Failed to parse current quote"
        )

    if detail_pattern is None:
        raise RuntimeError(
            "Failed to parse OHLCV"
        )

    current_price = float(
        quote_pattern.group(1).replace(",", "")
    )

    change = float(
        quote_pattern.group(2).replace(",", "")
    )

    change_pct = float(
        quote_pattern.group(3)
    )

    quote_time = quote_pattern.group(4)

    previous_close = float(
        detail_pattern.group(1).replace(",", "")
    )

    previous_close_date = detail_pattern.group(2)

    open_price = float(
        detail_pattern.group(3).replace(",", "")
    )

    high_price = float(
        detail_pattern.group(4).replace(",", "")
    )

    low_price = float(
        detail_pattern.group(5).replace(",", "")
    )

    volume = int(
        detail_pattern.group(6).replace(",", "")
    )

    print()
    print("=== PARSED MARKET DATA ===")
    print("Current price:", current_price)
    print("Change:", change)
    print("Change pct:", change_pct)
    print("Quote time:", quote_time)
    print("Previous close:", previous_close)
    print("Previous close date:", previous_close_date)
    print("Open:", open_price)
    print("High:", high_price)
    print("Low:", low_price)
    print("Volume:", volume)
    print()
    print("SUCCESS: Yahoo Japan page retrieved")


if __name__ == "__main__":
    main()
