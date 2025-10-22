from fastapi import FastAPI, HTTPException, Header, Query
from datetime import datetime, timezone
import os

from bank_controller import (
    AccountBalance,
    Transaction,
    FXRate,
    check_api_key as _check_api_key,
    get_balances as _get_balances,
    get_balance as _get_balance,
    get_transactions as _get_transactions,
    get_fx_rates as _get_fx_rates,
    startup as bank_startup,
    shutdown as bank_shutdown,
)
from sensor_controller import (
    load_sensor_records,
    startup as sensor_startup,
    shutdown as sensor_shutdown,
    load_web_records,
    current_warehouse_stock,
)

app = FastAPI(title="Demo Bank Balances API v2")


@app.on_event("startup")
async def startup():
    # Start controller background tasks
    await bank_startup(app)
    await sensor_startup(app)


@app.on_event("shutdown")
async def shutdown():
    await bank_shutdown(app)
    await sensor_shutdown(app)


API_KEY = os.environ.get("API_KEY", None)


def check_api_key(x_api_key: str | None):
    # Delegates to bank controller check (keeps behavior)
    _check_api_key(x_api_key)


@app.get("/balances", response_model=list[AccountBalance])
async def get_balances(x_api_key: str | None = Header(None)):
    """Returns current balances for all bank accounts in the system. Includes account identifiers,
    names, currencies, and last update timestamps."""
    check_api_key(x_api_key)
    return _get_balances()


@app.get("/balances/{account_id}", response_model=AccountBalance)
async def get_balance(account_id: str, x_api_key: str | None = Header(None)):
    """Returns the current balance for a specific bank account. Includes account details,
    currency, and last update timestamp."""
    check_api_key(x_api_key)
    return _get_balance(account_id)


@app.get("/transactions", response_model=list[Transaction])
async def get_transactions(
    account_id: str | None = None,
    limit: int = Query(100, le=1000),
    x_api_key: str | None = Header(None),
):
    """Returns transaction history showing debits and credits across accounts. Can be filtered
    by account. Each record includes amount, type, description, and resulting balance.
    """
    check_api_key(x_api_key)
    return _get_transactions(account_id=account_id, limit=limit)


@app.get("/fx/rates", response_model=list[FXRate])
async def get_fx_rates(x_api_key: str | None = Header(None)):
    """Returns current foreign exchange rates between supported currency pairs. Each rate
    includes source/target currencies and last update timestamp."""
    check_api_key(x_api_key)
    return _get_fx_rates()


@app.get("/occupancy")
async def get_occupancy(x_api_key: str | None = Header(None)):
    """Return office occupancy records collected over time. Each record shows staff count and
    max capacity per office location, with data points collected every 15 minutes."""
    check_api_key(x_api_key)
    return load_sensor_records()


@app.get("/web-traffic")
async def get_web_traffic(x_api_key: str | None = Header(None)):
    """Return web traffic metrics (website clicks, email volume, call center volume)."""
    check_api_key(x_api_key)
    return load_web_records()


@app.get("/warehouse-stock")
async def get_warehouse_stock(x_api_key: str | None = Header(None)):
    """Return simulated current warehouse stock for fixed product categories.
    This data is generated on each request and isn't persisted to disk."""
    check_api_key(x_api_key)
    return current_warehouse_stock()
