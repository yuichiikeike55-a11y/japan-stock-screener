"""
市場データ取得モジュールの設定。

ここに取得対象の市場指標を追加していく。

設計方針:
- 指標ごとの設定をここで一元管理する
- 取得処理そのものは別ファイルに分離する
- 将来、為替・米国指数・金利・VIX・商品などを追加できる形にする
"""


MARKET_DATA_ITEMS = [
    {
        "key": "nikkei225_futures_osaka",
        "name": "日経225先物（大阪）",
        "category": "futures",

        "primary": {
            "source": "yahoo_japan",
            "symbol": "5040469.O",
        },

        "fallback": None,

        "max_age_minutes": 180,
    },

    {
        "key": "nikkei225_futures_cme",
        "name": "CME日経225先物",
        "category": "futures",

        "primary": {
            "source": "yfinance",
            "symbol": "NKD=F",
        },

        "fallback": None,

        "max_age_minutes": 180,
    },
]


REQUIRED_OUTPUT_FIELDS = [
    "key",
    "name",
    "category",
    "symbol",
    "source",
    "value",
    "change",
    "change_pct",
    "as_of",
    "status",
]
