import math
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import requests

CRYPTO_API_URL = "https://api.coingecko.com/api/v3/simple/price"
QUOTE_CURRENCY = "usd"

CRYPTOCURRENCIES = {
    "bitcoin": ("Bitcoin", "BTC"),
    "ethereum": ("Ethereum", "ETH"),
    "solana": ("Solana", "SOL"),
    "dogecoin": ("Dogecoin", "DOGE"),
}

EXTRA_ASSETS = [
    {
        "symbol": "XAU",
        "name": "Gold",
        "ticker": "XAU/USD",
        "url": "https://api.gold-api.com/price/XAU",
        "unit": "USD / тройская унция",
        "source": "gold_api",
    },
    {
        "symbol": "CL=F",
        "name": "Нефть WTI",
        "ticker": "WTI",
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/CL%3DF",
        "unit": "USD / баррель",
        "source": "yahoo",
    },
    {
        "symbol": "BZ=F",
        "name": "Нефть Brent",
        "ticker": "BRENT",
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/BZ%3DF",
        "unit": "USD / баррель",
        "source": "yahoo",
    },
]

class DataSourceError(Exception):
    pass


def validate_price(price, asset_name):
    if (
        isinstance(price, bool)
        or not isinstance(price, (int, float))
        or not math.isfinite(price)
        or price <= 0
    ):
        raise DataSourceError(
            f"Источник вернул некорректную цену для {asset_name}."
        )
    return float(price)

def get_crypto_prices(coin_ids, currency="usd"):
    params = {
        "ids": ",".join(coin_ids),
        "vs_currencies": currency,
    }

    try:
        response = requests.get(
            CRYPTO_API_URL,
            params=params,
            timeout=10,
        )
    except requests.exceptions.Timeout as exc:
        raise DataSourceError(
            "Превышено время ожидания ответа CoinGecko."
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise DataSourceError(
            "Не удалось подключиться к CoinGecko. "
            "Проверьте интернет-соединение."
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise DataSourceError(
            f"Ошибка HTTP-запроса к CoinGecko: {exc}"
        ) from exc

    if response.status_code == 429:
        raise DataSourceError(
            "CoinGecko ограничил частоту запросов. Попробуйте позже."
        )

    if response.status_code in (401, 403):
        raise DataSourceError(
            "CoinGecko отказал в доступе. Проверьте доступность API."
        )

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        raise DataSourceError(
            f"CoinGecko вернул HTTP {response.status_code}."
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise DataSourceError(
            "CoinGecko вернул ответ, который не является корректным JSON."
        ) from exc

    if not isinstance(data, dict):
        raise DataSourceError(
            "Некорректный ответ CoinGecko: ожидался объект JSON."
        )

    prices = {}
    for coin_id in coin_ids:
        if coin_id not in data or not isinstance(data[coin_id], dict):
            raise DataSourceError(
                f"В ответе CoinGecko отсутствуют данные для {coin_id}."
            )

        if currency not in data[coin_id]:
            raise DataSourceError(
                f"В ответе CoinGecko отсутствует цена {coin_id} "
                f"в валюте {currency.upper()}."
            )

        prices[coin_id] = validate_price(
            data[coin_id][currency],
            coin_id,
        )

    return prices

def get_one_extra_asset(asset):
    try:
        response = requests.get(
            asset["url"],
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
    except requests.exceptions.Timeout as exc:
        raise DataSourceError(
            f"Истекло время ожидания для {asset['name']}."
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise DataSourceError(
            f"Нет соединения с источником данных для {asset['name']}."
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise DataSourceError(
            f"Ошибка запроса для {asset['name']}: {exc}"
        ) from exc

    if response.status_code == 429:
        raise DataSourceError(
            f"Превышен лимит запросов для {asset['name']}. "
            "Попробуйте позже."
        )

    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        raise DataSourceError(
            f"Источник {asset['name']} вернул HTTP "
            f"{response.status_code}."
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise DataSourceError(
            f"Источник {asset['name']} вернул некорректный JSON."
        ) from exc

    if not isinstance(data, dict):
        raise DataSourceError(
            f"Некорректный ответ источника для {asset['name']}."
        )

    if asset["source"] == "gold_api":
        price = data.get("price")
    else:
        chart = data.get("chart")
        if not isinstance(chart, dict):
            raise DataSourceError(
                f"В ответе Yahoo Finance отсутствует раздел chart "
                f"для {asset['name']}."
            )

        if chart.get("error"):
            raise DataSourceError(
                f"Yahoo Finance сообщил об ошибке для {asset['name']}."
            )

        results = chart.get("result")
        if not isinstance(results, list) or not results:
            raise DataSourceError(
                f"Yahoo Finance не вернул котировку для {asset['name']}."
            )

        meta = results[0].get("meta", {})
        if not isinstance(meta, dict):
            raise DataSourceError(
                f"Некорректные метаданные для {asset['name']}."
            )
        price = meta.get("regularMarketPrice")

    return validate_price(price, asset["name"])

def get_extra_prices():
    result = {}

    for asset in EXTRA_ASSETS:
        try:
            result[asset["symbol"]] = {
                "name": asset["name"],
                "ticker": asset["ticker"],
                "price": get_one_extra_asset(asset),
                "unit": asset["unit"],
                "error": None,
            }
        except DataSourceError as exc:
            result[asset["symbol"]] = {
                "name": asset["name"],
                "ticker": asset["ticker"],
                "price": None,
                "unit": asset["unit"],
                "error": str(exc),
            }

    return result

class CryptoTrackerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Мониторинг криптовалют, золота и нефти")
        self.root.geometry("900x470")
        self.root.minsize(700, 350)

        self.is_loading = False
        self.closing = False

        self.create_widgets()
        self.refresh_prices()

        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def create_widgets(self):
        title = ttk.Label(
            self.root,
            text="Мониторинг рыночных котировок",
            font=("Arial", 16, "bold"),
        )
        title.pack(pady=(15, 8))

        table_frame = ttk.Frame(self.root)
        table_frame.pack(
            fill="both",
            expand=True,
            padx=18,
            pady=5,
        )

        columns = ("name", "ticker", "price", "unit", "status")
        self.table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            height=10,
        )

        headings = {
            "name": "Актив",
            "ticker": "Тикер",
            "price": "Цена",
            "unit": "Валюта / единица",
            "status": "Состояние",
        }

        widths = {
            "name": 150,
            "ticker": 95,
            "price": 145,
            "unit": 200,
            "status": 160,
        }

        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(
                column,
                width=widths[column],
                anchor="w" if column in ("name", "unit", "status") else "center",
            )

        scrollbar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.table.yview,
        )
        self.table.configure(yscrollcommand=scrollbar.set)

        self.table.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.status_label = ttk.Label(
            self.root,
            text="Ожидание загрузки котировок...",
            anchor="w",
        )
        self.status_label.pack(fill="x", padx=20, pady=(8, 4))

        self.refresh_button = ttk.Button(
            self.root,
            text="Обновить котировки",
            command=self.refresh_prices,
        )
        self.refresh_button.pack(pady=(4, 14))

    def refresh_prices(self):
        if self.is_loading or self.closing:
            return

        self.is_loading = True
        self.refresh_button.config(state="disabled")
        self.status_label.config(text="Загрузка котировок...")
        thread = threading.Thread(target=self.load_prices, daemon=True)
        thread.start()

    def load_prices(self):
        crypto_prices = None
        crypto_error = None

        try:
            crypto_prices = get_crypto_prices(
                list(CRYPTOCURRENCIES.keys()),
                QUOTE_CURRENCY,
            )
        except DataSourceError as exc:
            crypto_error = str(exc)
        except Exception as exc:
            crypto_error = f"Непредвиденная ошибка крипто-API: {exc}"

        try:
            extra_prices = get_extra_prices()
        except Exception as exc:
            extra_prices = {}
            for asset in EXTRA_ASSETS:
                extra_prices[asset["symbol"]] = {
                    "name": asset["name"],
                    "ticker": asset["ticker"],
                    "price": None,
                    "unit": asset["unit"],
                    "error": f"Не удалось получить данные: {exc}",
                }

        if not self.closing:
            self.root.after(
                0,
                lambda: self.show_prices(crypto_prices, crypto_error, extra_prices),
            )

    def show_prices(self, crypto_prices, crypto_error, extra_prices):
        try:
            for item in self.table.get_children():
                self.table.delete(item)

            errors = []

            for coin_id, (name, ticker) in CRYPTOCURRENCIES.items():
                if crypto_prices is not None:
                    price = crypto_prices[coin_id]
                    price_text = f"{price:,.8f}".rstrip("0").rstrip(".")
                    status = "Доступно"
                else:
                    price_text = "Нет данных"
                    status = "Ошибка"
                    if crypto_error and crypto_error not in errors:
                        errors.append(crypto_error)

                self.table.insert(
                    "",
                    "end",
                    values=(
                        name,
                        ticker,
                        price_text,
                        QUOTE_CURRENCY.upper(),
                        status,
                    ),
                )

            for asset in EXTRA_ASSETS:
                item = extra_prices.get(asset["symbol"], {})
                error = item.get("error")

                if error:
                    price_text = "Нет данных"
                    status = "Ошибка"
                    if error not in errors:
                        errors.append(error)
                else:
                    price = item.get("price")
                    price_text = f"{price:,.2f}" if price is not None else "Нет данных"
                    status = "Доступно" if price is not None else "Ошибка"

                self.table.insert(
                    "",
                    "end",
                    values=(
                        item.get("name", asset["name"]),
                        item.get("ticker", asset["ticker"]),
                        price_text,
                        item.get("unit", asset["unit"]),
                        status,
                    ),
                )

            if errors:
                self.status_label.config(
                    text="Некоторые котировки недоступны. Подробности в сообщении."
                )
                messagebox.showwarning(
                    "Проблемы с котировками",
                    "\n\n".join(errors),
                    parent=self.root,
                )
            else:
                self.status_label.config(
                    text="Все котировки успешно обновлены"
                )

            if not self.table.get_children():
                self.status_label.config(
                    text="Котировки не отображаются. Нажмите «Обновить котировки»."
                )
        finally:
            self.is_loading = False
            if not self.closing:
                self.refresh_button.config(state="normal")

    def close(self):
        self.closing = True
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = CryptoTrackerApp(root)
    root.mainloop()
