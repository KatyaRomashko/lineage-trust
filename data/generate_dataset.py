"""
Generate a synthetic customer-churn CSV that will be seeded into MinIO.

Uses only the standard library so it can run without any pip install.

Fields
------
entity_id            – unique customer identifier
event_timestamp      – when the observation was recorded
tenure_months        – months with the service
monthly_charges      – monthly bill ($)
total_charges        – cumulative charges ($)
num_support_tickets  – support tickets opened
contract_type        – Month-to-month / One-year / Two-year
internet_service     – DSL / Fiber optic / No
payment_method       – Electronic check / Mailed check / Bank transfer / Credit card
churn                – 1 = churned, 0 = retained  (target)
"""

import csv
import math
import os
import random
from datetime import datetime, timedelta

SEED = 42
N_ROWS = 2000

random.seed(SEED)

contracts = ["Month-to-month", "One-year", "Two-year"]
internet_options = ["DSL", "Fiber optic", "No"]
payment_methods = [
    "Electronic check",
    "Mailed check",
    "Bank transfer",
    "Credit card",
]

base_ts = datetime(2024, 1, 1)

out_path = os.path.join(os.path.dirname(__file__), "customers.csv")

with open(out_path, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow([
        "entity_id", "event_timestamp", "tenure_months", "monthly_charges",
        "total_charges", "num_support_tickets", "contract_type",
        "internet_service", "payment_method", "churn",
    ])

    for i in range(1, N_ROWS + 1):
        tenure = random.randint(1, 71)
        monthly = round(random.uniform(18.0, 120.0), 2)
        total = round(monthly * tenure + random.gauss(0, 50), 2)
        total = max(total, 0)
        # Poisson-ish via inverse-transform (lambda=1.5)
        tickets = 0
        L = math.exp(-1.5)
        p_val = 1.0
        while True:
            p_val *= random.random()
            if p_val < L:
                break
            tickets += 1

        contract = random.choice(contracts)
        internet = random.choice(internet_options)
        payment = random.choice(payment_methods)

        # Churn probability rises with monthly charges and tickets
        logit = 0.02 * monthly + 0.3 * tickets - 0.05 * tenure - 3
        prob = 1 / (1 + math.exp(-logit))
        churn = 1 if random.random() < prob else 0

        ts = base_ts + timedelta(days=random.randint(0, 179), hours=random.randint(0, 23))

        total_val = total
        monthly_val = monthly

        # Sprinkle ~3% nulls on total_charges, ~2% on monthly_charges
        if random.random() < 0.03:
            total_val = ""
        if random.random() < 0.02:
            monthly_val = ""

        writer.writerow([
            i, ts.isoformat(), tenure, monthly_val, total_val,
            tickets, contract, internet, payment, churn,
        ])

print(f"Generated {N_ROWS} rows → {out_path}")
