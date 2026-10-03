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

    response = requests.get(
        url,
        headers=headers,
        timeout=20,
    )

    print("HTTP status:", response.status_code)

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

    print()
    print("SUCCESS: Yahoo Japan page retrieved")


if __name__ == "__main__":
    main()
    print("SUCCESS:", ticker)


if __name__ == "__main__":
    main()
