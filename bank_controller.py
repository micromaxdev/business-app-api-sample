from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional, Literal
from enum import Enum
import asyncio
import random
import json
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal, ROUND_HALF_UP
import os

# Data dir
DATA_DIR = Path("./bank_data")
DATA_DIR.mkdir(exist_ok=True)

TRANSACTIONS_FILE = DATA_DIR / "transactions.jsonl"
PAYMENTS_FILE = DATA_DIR / "payments.json"
ALERTS_FILE = DATA_DIR / "alerts.json"


# ==================== Models ====================


class AccountBalance(BaseModel):
    account_id: str
    account_name: str
    currency: str
    balance: str
    last_updated: str


class Transaction(BaseModel):
    transaction_id: str
    account_id: str
    timestamp: str
    amount: str
    type: Literal["debit", "credit"]
    description: str
    balance_after: str
    currency: str


class PaymentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Payment(BaseModel):
    payment_id: str
    from_account: str
    to_reference: str
    amount: str
    currency: str
    status: PaymentStatus
    created_at: str
    processed_at: Optional[str] = None
    description: str


class CashFlowSummary(BaseModel):
    account_id: str
    period: str
    total_inflows: str
    total_outflows: str
    net_flow: str
    transaction_count: int
    currency: str


class Alert(BaseModel):
    alert_id: str
    account_id: str
    severity: Literal["low", "medium", "high"]
    message: str
    timestamp: str
    acknowledged: bool = False


class FXRate(BaseModel):
    from_currency: str
    to_currency: str
    rate: str
    last_updated: str


# ==================== Data Storage ====================

# In-memory stores
ACCOUNTS = {
    "op_aud": {
        "account_id": "op_aud",
        "account_name": "Operating Account",
        "currency": "AUD",
        "balance": Decimal("16532.45"),
    },
    "sav_aud": {
        "account_id": "sav_aud",
        "account_name": "Savings Account",
        "currency": "AUD",
        "balance": Decimal("120432.10"),
    },
    "exp_usd": {
        "account_id": "exp_usd",
        "account_name": "Export Reserve",
        "currency": "USD",
        "balance": Decimal("8750.67"),
    },
}

PENDING_PAYMENTS = []
ALERTS = []
FX_RATES = {"AUD_USD": Decimal("0.65"), "USD_AUD": Decimal("1.54")}

# Counters
TRANSACTION_COUNTER = 0
PAYMENT_COUNTER = 0
ALERT_COUNTER = 0


# ==================== Helpers ====================


def quantize_amount(d: Decimal):
    return str(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def generate_transaction_id():
    global TRANSACTION_COUNTER
    TRANSACTION_COUNTER += 1
    return f"TXN{TRANSACTION_COUNTER:08d}"


def generate_payment_id():
    global PAYMENT_COUNTER
    PAYMENT_COUNTER += 1
    return f"PAY{PAYMENT_COUNTER:08d}"


def generate_alert_id():
    global ALERT_COUNTER
    ALERT_COUNTER += 1
    return f"ALT{ALERT_COUNTER:08d}"


def save_transaction(txn_dict):
    """Append transaction to JSONL file"""
    with open(TRANSACTIONS_FILE, "a") as f:
        f.write(json.dumps(txn_dict) + "\n")


def load_transactions():
    """Load all transactions from file"""
    if not TRANSACTIONS_FILE.exists():
        return []
    transactions = []
    with open(TRANSACTIONS_FILE, "r") as f:
        for line in f:
            if line.strip():
                transactions.append(json.loads(line))
    return transactions


def save_payments():
    """Save payments to JSON file"""
    with open(PAYMENTS_FILE, "w") as f:
        json.dump(
            [p.__dict__ if hasattr(p, "__dict__") else p for p in PENDING_PAYMENTS],
            f,
            indent=2,
        )


def load_payments():
    """Load payments from JSON file"""
    if not PAYMENTS_FILE.exists():
        return []
    with open(PAYMENTS_FILE, "r") as f:
        return json.load(f)


def save_alerts():
    """Save alerts to JSON file"""
    with open(ALERTS_FILE, "w") as f:
        json.dump(
            [a.__dict__ if hasattr(a, "__dict__") else a for a in ALERTS], f, indent=2
        )


def load_alerts():
    """Load alerts from JSON file"""
    if not ALERTS_FILE.exists():
        return []
    with open(ALERTS_FILE, "r") as f:
        return json.load(f)


def record_transaction(
    account_id: str, amount: Decimal, txn_type: str, description: str
):
    """Record a transaction and save to file"""
    acct = ACCOUNTS[account_id]
    txn = {
        "transaction_id": generate_transaction_id(),
        "account_id": account_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "amount": quantize_amount(abs(amount)),
        "type": txn_type,
        "description": description,
        "balance_after": quantize_amount(acct["balance"]),
        "currency": acct["currency"],
    }
    save_transaction(txn)
    return txn


def check_alerts(account_id: str):
    """Check and create alerts for an account"""
    acct = ACCOUNTS[account_id]
    balance = acct["balance"]

    # Low balance alert
    if balance < Decimal("5000") and acct["currency"] == "AUD":
        alert = {
            "alert_id": generate_alert_id(),
            "account_id": account_id,
            "severity": "high" if balance < Decimal("2000") else "medium",
            "message": f"Low balance warning: {acct['account_name']} has {quantize_amount(balance)} {acct['currency']}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }
        ALERTS.append(alert)
        save_alerts()

    # Overdraft alert
    if balance < Decimal("0"):
        alert = {
            "alert_id": generate_alert_id(),
            "account_id": account_id,
            "severity": "high",
            "message": f"OVERDRAFT: {acct['account_name']} is {quantize_amount(abs(balance))} {acct['currency']} overdrawn",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }
        ALERTS.append(alert)
        save_alerts()


# ==================== Background Tasks ====================


async def balance_simulator():
    """Random-walk style updates to balances"""
    try:
        while True:
            acct_key = random.choice(list(ACCOUNTS.keys()))
            acct = ACCOUNTS[acct_key]
            base = acct["balance"]

            # Generate realistic change
            if acct_key == "op_aud":
                if random.random() < 0.3:
                    change = Decimal(random.uniform(-3000, 5000)).quantize(
                        Decimal("0.01")
                    )
                    desc = random.choice(
                        [
                            "Customer payment received",
                            "Supplier payment",
                            "Payroll transfer",
                            "Tax payment",
                            "Utility bill",
                        ]
                    )
                else:
                    vol_pct = random.uniform(-0.02, 0.03)
                    change = (base * Decimal(str(vol_pct))).quantize(Decimal("0.01"))
                    desc = "Operating activity"
            elif acct_key == "sav_aud":
                change = Decimal(random.uniform(-500, 2000)).quantize(Decimal("0.01"))
                desc = "Interest earned" if change > 0 else "Transfer to operating"
            else:  # exp_usd
                if random.random() < 0.15:
                    change = Decimal(random.uniform(500, 8000)).quantize(
                        Decimal("0.01")
                    )
                    desc = "Export receipt"
                else:
                    change = Decimal(random.uniform(-200, 500)).quantize(
                        Decimal("0.01")
                    )
                    desc = "International payment"

            acct["balance"] = (acct["balance"] + change).quantize(Decimal("0.01"))
            if acct["balance"] < Decimal("-5000"):
                acct["balance"] = Decimal("-5000.00")

            acct["last_updated"] = datetime.now(timezone.utc).isoformat()

            # Record transaction
            txn_type = "credit" if change > 0 else "debit"
            record_transaction(acct_key, change, txn_type, desc)

            # Check for alerts
            check_alerts(acct_key)

            await asyncio.sleep(random.uniform(20, 90))
    except asyncio.CancelledError:
        return


async def payment_processor():
    """Process pending payments"""
    try:
        while True:
            await asyncio.sleep(15)  # Check every 15 seconds

            for payment in PENDING_PAYMENTS[:]:
                if payment["status"] != "pending":
                    continue

                # Simulate processing delay
                created = datetime.fromisoformat(payment["created_at"])
                age = (datetime.now(timezone.utc) - created).total_seconds()

                if age > 30:  # Process after 30 seconds
                    payment["status"] = "processing"
                    save_payments()

                if age > 60:  # Complete after 60 seconds
                    # Deduct from account
                    from_acct = payment["from_account"]
                    if from_acct in ACCOUNTS:
                        amount = Decimal(payment["amount"])
                        ACCOUNTS[from_acct]["balance"] -= amount

                        record_transaction(
                            from_acct,
                            -amount,
                            "debit",
                            f"Payment to {payment['to_reference']}: {payment['description']}",
                        )

                        check_alerts(from_acct)

                    payment["status"] = "completed"
                    payment["processed_at"] = datetime.now(timezone.utc).isoformat()
                    save_payments()
    except asyncio.CancelledError:
        return


async def fx_rate_updater():
    """Update FX rates periodically"""
    try:
        while True:
            await asyncio.sleep(120)  # Update every 2 minutes

            # Simulate small FX movements
            for pair in FX_RATES:
                current = FX_RATES[pair]
                change_pct = Decimal(str(random.uniform(-0.005, 0.005)))  # +/- 0.5%
                new_rate = (current * (Decimal("1") + change_pct)).quantize(
                    Decimal("0.0001")
                )
                FX_RATES[pair] = new_rate
    except asyncio.CancelledError:
        return


# ==================== Lifecycle helpers ====================


def check_api_key(x_api_key: str | None):
    API_KEY = os.environ.get("API_KEY", None)
    if API_KEY:
        if not x_api_key or x_api_key != API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")


def get_balances():
    out = []
    for acct in ACCOUNTS.values():
        out.append(
            AccountBalance(
                account_id=acct["account_id"],
                account_name=acct["account_name"],
                currency=acct["currency"],
                balance=quantize_amount(acct["balance"]),
                last_updated=acct.get(
                    "last_updated", datetime.now(timezone.utc).isoformat()
                ),
            )
        )
    return out


def get_balance(account_id: str):
    acct = ACCOUNTS.get(account_id)
    if not acct:
        raise HTTPException(status_code=404, detail="Account not found")
    return AccountBalance(
        account_id=acct["account_id"],
        account_name=acct["account_name"],
        currency=acct["currency"],
        balance=quantize_amount(acct["balance"]),
        last_updated=acct.get("last_updated", datetime.now(timezone.utc).isoformat()),
    )


def get_transactions(account_id: Optional[str] = None, limit: int = 100):
    all_txns = load_transactions()
    if account_id:
        all_txns = [t for t in all_txns if t["account_id"] == account_id]
    all_txns = all_txns[-limit:][::-1]
    return [Transaction(**t) for t in all_txns]


def get_fx_rates():
    rates = []
    for pair, rate in FX_RATES.items():
        from_curr, to_curr = pair.split("_")
        rates.append(
            FXRate(
                from_currency=from_curr,
                to_currency=to_curr,
                rate=quantize_amount(rate),
                last_updated=datetime.now(timezone.utc).isoformat(),
            )
        )
    return rates


async def startup(app):
    global PENDING_PAYMENTS, ALERTS, TRANSACTION_COUNTER

    PENDING_PAYMENTS = load_payments()
    ALERTS = load_alerts()

    transactions = load_transactions()
    if transactions:
        TRANSACTION_COUNTER = len(transactions)

    app.state.simulator_task = asyncio.create_task(balance_simulator())
    app.state.payment_task = asyncio.create_task(payment_processor())
    app.state.fx_task = asyncio.create_task(fx_rate_updater())


async def shutdown(app):
    for task_name in ["simulator_task", "payment_task", "fx_task"]:
        task = getattr(app.state, task_name, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
