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
    # Price data diagnostic
    # =====================================

    labels = [
        "前日終値",
        "始値",
        "高値",
        "安値",
        "出来高",
    ]

    print()
    print("=== PRICE DATA DIAGNOSTIC ===")

    for label in labels:
        position = text.find(label)

        print()
        print("LABEL:", label)
        print("POSITION:", position)

        if position >= 0:
            start = max(
                0,
                position - 100,
            )

            end = min(
                len(text),
                position + 250,
            )

            print(
                text[start:end]
            )
        else:
            print(
                "NOT FOUND"
            )
    print()
    print("SUCCESS: Yahoo Japan page retrieved")


if __name__ == "__main__":
    main()
