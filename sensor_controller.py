import asyncio
import random
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List

DATA_DIR = Path("./bank_data")
DATA_DIR.mkdir(exist_ok=True)

SENSORS_FILE = DATA_DIR / "sensors.jsonl"
WEB_FILE = DATA_DIR / "web.jsonl"


OFFICES = [
    "Wollongong - Head Office",
    "Melbourne - Sales Hub",
    "Brisbane - Regional Office",
    "Perth - Support Centre",
    "Adelaide - Field Team",
    "Auckland - NZ Branch",
    "Wellington - NZ Support",
    "New York - US Sales",
    "London - EMEA Office",
]


def current_slot_weight(hour: int, office: str) -> float:
    """Return a weight multiplier for expected occupancy based on hour and office."""
    # Day parts:
    # 6-9 rising, 9-15 steady, 15-19 falling, night otherwise
    if 6 <= hour < 9:
        base = 0.6
    elif 9 <= hour < 15:
        base = 0.9
    elif 15 <= hour < 19:
        base = 0.5
    else:
        base = 0.05

    # Some offices (HQ, Sales hubs) have higher occupancy
    if "Head" in office or "Sales" in office:
        base *= 1.2
    # Overseas offices might be lower due to timezone mismatch
    if "New York" in office or "London" in office:
        base *= 0.7

    return max(0.0, min(1.0, base))


def simulate_office_record(office: str) -> dict:
    """Simulate occupancy for a single office at current time."""
    now = datetime.now(timezone.utc)
    local_hour = (
        now.hour
    )  # Using UTC hour is acceptable for simulation; could be extended
    weight = current_slot_weight(local_hour, office)

    # Each office has a nominal capacity
    capacity_map = {
        "Head Office": 200,
        "Sales Hub": 120,
        "Regional Office": 80,
        "Support Centre": 60,
        "Field Team": 30,
        "NZ Branch": 50,
        "US Sales": 90,
        "EMEA Office": 70,
    }

    nominal = 50
    for key in capacity_map:
        if key in office:
            nominal = capacity_map[key]
            break

    # Introduce randomness around the weighted nominal
    mean = int(nominal * weight)
    # During high ramp up hours, increase variance positive
    if 6 <= local_hour < 9:
        variance = int(nominal * 0.25)
    elif 9 <= local_hour < 15:
        variance = int(nominal * 0.1)
    elif 15 <= local_hour < 19:
        variance = int(nominal * 0.2)
    else:
        variance = int(nominal * 0.05)

    count = max(
        0, random.randint(max(0, mean - variance), min(nominal, mean + variance))
    )

    # Occasionally, night-activity: a few offices have 1-5 staff
    if mean == 0 and random.random() < 0.02:
        count = random.randint(1, 5)

    return {
        "timestamp": now.isoformat(),
        "office": office,
        "occupancy": count,
        "capacity": nominal,
    }


async def sensor_job():
    try:
        while True:
            # Run every 15 minutes
            now = datetime.now(timezone.utc)

            # Generate and save occupancy records
            records = [simulate_office_record(o) for o in OFFICES]
            with open(SENSORS_FILE, "a", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r) + "\n")

            # Maybe generate and save web traffic (33.33% chance)
            web_record = simulate_web_traffic()
            if web_record:
                with open(WEB_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(web_record) + "\n")

            # Sleep until next 15-minute boundary to keep timing aligned
            await asyncio.sleep(15 * 60)
    except asyncio.CancelledError:
        return


def load_sensor_records() -> List[dict]:
    if not SENSORS_FILE.exists():
        return []
    out = []
    with open(SENSORS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def load_web_records() -> List[dict]:
    """Load web traffic records from web.jsonl"""
    if not WEB_FILE.exists():
        return []
    out = []
    with open(WEB_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def simulate_web_traffic() -> dict | None:
    """Simulate web traffic metrics with day-of-week weighting.
    Returns None 66.67% of the time to achieve desired probability."""

    # 33.33% chance of generating data
    if random.random() > 0.3333:
        return None

    now = datetime.now(timezone.utc)
    weekday = now.weekday()  # Monday is 0, Sunday is 6

    # Base multipliers for different channels
    BASE_CLICKS = 1000
    BASE_EMAILS = 200
    BASE_CALLS = 50

    # Day of week weights
    if weekday < 5:  # Mon-Fri
        day_weight = random.uniform(0.8, 1.2)  # High variance on weekdays
    else:  # Sat-Sun
        day_weight = random.uniform(0.1, 0.3)  # Much lower weekend activity

    # Add time-of-day variation (assuming business hours ~8 hours)
    hour = now.hour
    if 8 <= hour < 16:  # Business hours
        time_weight = random.uniform(0.8, 1.5)
    elif 6 <= hour < 8 or 16 <= hour < 18:  # Shoulder periods
        time_weight = random.uniform(0.3, 0.8)
    else:  # Off hours
        time_weight = random.uniform(0.05, 0.2)

    # Combine weights and add high variance
    weight = day_weight * time_weight

    # Generate numbers with different variance levels
    clicks = int(BASE_CLICKS * weight * random.uniform(0.6, 2.0))  # Highest variance
    emails = int(BASE_EMAILS * weight * random.uniform(0.7, 1.6))  # Medium variance
    calls = int(BASE_CALLS * weight * random.uniform(0.8, 1.4))  # Lower variance

    return {
        "website_clicks": clicks,
        "emails": emails,
        "calls": calls,
        "timestamp": now.isoformat(),
    }


# In-memory state for warehouse stock simulation. Kept simple and module-level so
# subsequent calls to the function will see previous state and allow gentle drift.
_WAREHOUSE_CATEGORIES = [
    "Medical Carts",
    "Embedded Computers",
    "Routers",
    "Media Players",
]

# Initialize a nominal steady level for each category.
_warehouse_state = {
    "Medical Carts": 120,
    "Embedded Computers": 240,
    "Routers": 360,
    "Media Players": 180,
}


def current_warehouse_stock() -> dict:
    """Simulate current warehouse stock for fixed categories.

    Behavior:
    - Small random walk (±0-3 units) per call to simulate trickle changes.
    - 1/20 chance of a large downward spike (drop 30-60% of stock) representing a big sale or loss.
      When a spike occurs, the function will include an "order" field indicating a replenishment
      action that returns stock to a steady level for that category.
    - State is kept in the module so consecutive API calls show continuity. Nothing is written
      to disk.
    """
    global _warehouse_state

    now = datetime.now(timezone.utc).isoformat()
    out = {"timestamp": now, "items": []}

    for cat in _WAREHOUSE_CATEGORIES:
        current = _warehouse_state.get(cat, 100)

        # Occasionally trigger a large downward spike
        if random.random() < 1 / 20:
            # Drop between 30% and 60%
            drop_pct = random.uniform(0.3, 0.6)
            dropped = max(0, int(current * (1 - drop_pct)))
            # Record the spike and simulate an immediate order to bring it back to nominal
            nominal = current  # assume nominal was the last seen level
            # place order to restore to nominal
            _warehouse_state[cat] = nominal
            out["items"].append(
                {
                    "category": cat,
                    "stock": dropped,
                    "event": "spike_down_and_ordered",
                    "ordered_to": nominal,
                }
            )
            continue

        # Small drift: -3..+3
        drift = random.randint(-3, 3)
        new_val = max(0, current + drift)

        # update state
        _warehouse_state[cat] = new_val

        out["items"].append({"category": cat, "stock": new_val})

    return out


async def startup(app):
    # Start background sensor job
    app.state.sensor_task = asyncio.create_task(sensor_job())


async def shutdown(app):
    task = getattr(app.state, "sensor_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
