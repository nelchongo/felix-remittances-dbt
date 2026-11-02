#!/usr/bin/env python3
"""
Generate synthetic source extracts for the Félix remittances take-home.

Produces four CSVs that mimic raw backend exports (CDC-style, append-only):
    users.csv, payments.csv, receipts.csv, disbursements.csv

Output layout
-------------
    data/source/                       baseline extract up to BASELINE_END (stand-in for Félix's files, never edited)
    data/test_batches/<YYYY-MM>/       later monthly increments: new rows + late updates to old records
                                       (KYC changes, chargebacks on old payments, beneficiary changes, in-flight payouts)
    data/test_batches/edge_cases/      a few hand-crafted bad rows to exercise the data tests
    data/landing/<table>/              working copy read by the loader. Starts as a copy of data/source.
                                       Add batches or hand-edit freely (`python run.py reset-data` restores it)

Business shape
--------------
* Pay-in: **debit card** (online, through a card processor, funded by the customer's US bank)
          or **cash** (barcode paid at a US store through a cash network).
  Two pay-in "providers" per payment: `payment_processor` (who collects the money for Félix) and
  `funding_institution` (where the money comes from: the issuing bank, or the store where cash was paid).
* Fees follow Félix's public pricing: $2.99 to a bank/wallet, $4.98 to cash pickup; cash pay-in adds a
  $3.98 store commission (pass-through, not Félix revenue). FX revenue = spread vs a reference mid-market rate.
* Skewed volume, personas, households/mule clusters, provider failure differences, chargebacks (cards only),
  cash barcodes that expire unpaid, seasonality (December, Mother's Day), SCD2 changes on users and beneficiaries.
* Intentional data-quality issues (see DATA_QUALITY).

Processor / bank / store names are illustrative examples of the US market, not Félix's actual partners.

Usage
-----
    python src/generate_sample_data.py --users 2500 --seed 42
"""
from __future__ import annotations

import argparse
import csv
import math
import random
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

# --------------------------------------------------------------------------------------
# Time windows
# --------------------------------------------------------------------------------------
START = datetime(2024, 7, 1, tzinfo=UTC)                 # first transaction (24 months of baseline -> YoY)
BASELINE_END = datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC)  # cut-off of data/source
END = datetime(2026, 9, 30, 23, 59, 59, tzinfo=UTC)      # end of simulation (test batches)
TABLES = ["users", "payments", "receipts", "disbursements"]

# --------------------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------------------
FIRST_NAMES = [
    "José", "María", "Juan", "Guadalupe", "Luis", "Ana", "Carlos", "Rosa", "Jorge", "Carmen",
    "Miguel", "Verónica", "Pedro", "Lucía", "Francisco", "Elena", "Alejandro", "Patricia",
    "Ricardo", "Sofía", "Fernando", "Gabriela", "Raúl", "Daniela", "Héctor", "Adriana",
    "Javier", "Mónica", "Roberto", "Claudia", "Eduardo", "Leticia", "Óscar", "Isabel",
    "Manuel", "Teresa", "Sergio", "Silvia", "Andrés", "Yesenia",
]
LAST_NAMES = [
    "Hernández", "García", "Martínez", "López", "González", "Pérez", "Rodríguez", "Sánchez",
    "Ramírez", "Cruz", "Flores", "Gómez", "Morales", "Vázquez", "Reyes", "Jiménez", "Torres",
    "Díaz", "Gutiérrez", "Ruiz", "Mendoza", "Aguilar", "Ortiz", "Castillo", "Romero",
    "Álvarez", "Chávez", "Ramos", "Herrera", "Medina",
]
US_STATES = [("CA", 30), ("TX", 22), ("IL", 7), ("FL", 7), ("AZ", 6), ("NY", 6), ("GA", 4),
             ("NC", 4), ("WA", 3), ("NV", 3), ("CO", 3), ("NJ", 3), ("OR", 2)]
EMAIL_DOMAINS = ["gmail.com", "hotmail.com", "yahoo.com", "outlook.com", "icloud.com"]

# destination country -> (currency, weight, base fx per USD, monthly drift)
DESTINATIONS = {
    "MX": ("MXN", 62, 18.40, 0.004),
    "GT": ("GTQ", 14, 7.72, 0.000),
    "HN": ("HNL", 8, 25.10, 0.002),
    "SV": ("USD", 6, 1.00, 0.000),
    "CO": ("COP", 5, 4050.0, -0.006),
    "DO": ("DOP", 5, 60.20, 0.003),
}
# FX spread Félix keeps vs the reference (mid-market) rate; SV is USD->USD so no spread
FX_SPREAD = {"MX": (0.006, 0.015), "GT": (0.008, 0.018), "HN": (0.008, 0.020),
             "SV": (0.0, 0.0), "CO": (0.010, 0.022), "DO": (0.009, 0.020)}

# ---- Pay-in -----------------------------------------------------------------------------
# debit card: issuing bank (funding institution) -> (weight, decline-rate multiplier, chargeback multiplier)
ISSUING_BANKS = {
    "JPMorgan Chase":  (20, 0.9, 0.9),
    "Bank of America": (18, 1.0, 1.0),
    "Wells Fargo":     (16, 1.0, 1.1),
    "Citibank":        (8, 0.9, 0.8),
    "U.S. Bank":       (5, 1.0, 1.0),
    "Capital One":     (6, 0.8, 0.8),
    "PNC Bank":        (4, 1.0, 1.0),
    "Truist":          (3, 1.1, 1.0),
    "TD Bank":         (3, 1.0, 1.0),
    "Chime":           (17, 1.8, 2.2),   # neobank: popular with first-time bankers, higher declines & disputes
}
BANK_TYPE = {b: ("neobank" if b == "Chime" else "bank") for b in ISSUING_BANKS}
# cash: retailer where the barcode is paid (funding institution) -> (weight, expiry multiplier)
RETAILERS = {
    "7-Eleven": (26, 1.0), "Walmart": (22, 0.8), "CVS Pharmacy": (16, 1.0),
    "Family Dollar": (14, 1.2), "Dollar General": (10, 1.2), "Walgreens": (7, 1.0), "ACE Cash Express": (5, 0.9),
}
# payment processors (who collects the money on behalf of Félix) -> base failure probability
CARD_PROCESSORS = {"Adyen": (55, 0.050), "Stripe": (45, 0.065)}
CASH_NETWORKS = {"PayNearMe": (100, 0.0)}
CARD_FAILURE_REASONS = [("card_declined", 40), ("insufficient_funds", 35), ("risk_blocked", 15),
                        ("3ds_failed", 10)]
CASH_EXPIRY_P = 0.14          # barcode generated but never paid at the store
CASH_MAX_USD = 1000.0         # typical per-barcode cash limit
CARD_MAX_USD = 2000.0         # Félix limit per transfer
STORE_FEE_USD = 3.98          # store commission on cash pay-in (pass-through)
FEE_BY_PAYOUT = {"bank_deposit": 2.99, "mobile_wallet": 2.99, "cash_pickup": 4.98}

# ---- Payout (disbursement) providers: fictional -----------------------------------------
PROVIDERS = {
    "Pagos Express": 0.020, "RemesaNet": 0.055, "CashPoint LatAm": 0.140, "Banco Puente": 0.030,
    "Lempira Pay": 0.050, "CuscaTransfer": 0.035, "Andes Payouts": 0.090, "Caribe Remit": 0.190,
}
ROUTING = {
    "MX": [("Pagos Express", 55), ("RemesaNet", 30), ("CashPoint LatAm", 15)],
    "GT": [("Banco Puente", 70), ("CashPoint LatAm", 30)],
    "HN": [("Lempira Pay", 75), ("CashPoint LatAm", 25)],
    "SV": [("CuscaTransfer", 100)],
    "CO": [("Andes Payouts", 100)],
    "DO": [("Caribe Remit", 80), ("CashPoint LatAm", 20)],
}
PAYOUT_METHODS = [("bank_deposit", 55), ("cash_pickup", 30), ("mobile_wallet", 15)]
DISB_FAILURE_REASONS = [("invalid_account", 30), ("beneficiary_name_mismatch", 20),
                        ("provider_timeout", 25), ("compliance_hold", 10),
                        ("insufficient_provider_liquidity", 15)]

# persona -> (share of users, mean send USD, lognormal sigma)
PERSONAS = {
    "inactive": (0.10, 0, 0),
    "one_time": (0.34, 220, 0.55),
    "occasional": (0.28, 280, 0.55),
    "monthly": (0.21, 360, 0.45),
    "heavy": (0.07, 950, 0.40),
}

DATA_QUALITY = {
    "exact_duplicate_rate": 0.015,
    "status_casing_rate": 0.05,
    "naive_timestamp_rate": 0.03,
    "thousands_sep_rate": 0.30,
    "email_casing_rate": 0.10,
    "orphan_receipts": 4,
}


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def wchoice(rng: random.Random, pairs):
    items, weights = zip(*pairs)
    return rng.choices(items, weights=weights, k=1)[0]


def gen_id(rng: random.Random, prefix: str) -> str:
    return f"{prefix}_{rng.getrandbits(64):016x}"


def fmt_ts(rng: random.Random, ts: datetime) -> str:
    if rng.random() < DATA_QUALITY["naive_timestamp_rate"]:
        return ts.strftime("%Y-%m-%d %H:%M:%S")
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def fmt_amount(rng: random.Random, amount: float) -> str:
    if amount >= 1000 and rng.random() < DATA_QUALITY["thousands_sep_rate"]:
        return f"{amount:,.2f}"
    return f"{amount:.2f}"


def messy_status(rng: random.Random, status: str) -> str:
    if rng.random() < DATA_QUALITY["status_casing_rate"]:
        return rng.choice([status.upper(), status.capitalize(), f" {status}", f"{status} "])
    return status


def rand_ts(rng: random.Random, lo: datetime, hi: datetime) -> datetime:
    span = (hi - lo).total_seconds()
    ts = lo + timedelta(seconds=rng.uniform(0, max(span, 1)))
    if rng.random() < 0.5:  # evenings / late night US time
        ts = ts.replace(hour=rng.choice([0, 1, 2, 3, 23, 22, 21, 20, 19, 18]))
    return ts.replace(microsecond=rng.randrange(0, 1_000_000))


def lognormal_amount(rng: random.Random, mean: float, sigma: float, cap: float) -> float:
    mu = math.log(mean) - sigma ** 2 / 2
    amt = rng.lognormvariate(mu, sigma)
    if rng.random() < 0.55:
        amt = round(amt / 50) * 50 or 50
    return round(min(max(amt, 10.0), cap), 2)


def reference_rate(rng: random.Random, country: str, ts: datetime) -> float:
    _, _, base, drift = DESTINATIONS[country]
    months = (ts - START).days / 30.4
    return base * (1 + drift) ** months * (1 + rng.uniform(-0.004, 0.004))


def parse_ts(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


# --------------------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------------------
@dataclass
class Beneficiary:
    beneficiary_id: str
    first_name: str
    last_name: str
    country: str
    payout_method: str
    account_last4: str | None
    change_at: datetime | None = None          # SCD2 driver
    new_payout_method: str | None = None
    new_account_last4: str | None = None

    def as_of(self, ts: datetime) -> tuple[str, str | None]:
        if self.change_at and ts >= self.change_at:
            return self.new_payout_method, self.new_account_last4
        return self.payout_method, self.account_last4


@dataclass
class User:
    user_id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    state: str
    signup_at: datetime
    kyc_status: str
    persona: str
    pay_pref: str                       # card_only | cash_only | mixed
    bank: str                           # issuing bank of their debit card
    card_last4: str
    stores: list[str] = field(default_factory=list)
    is_mule_sender: bool = False
    beneficiaries: list[Beneficiary] = field(default_factory=list)


def make_beneficiary(rng: random.Random, last_name: str | None = None,
                     country: str | None = None) -> Beneficiary:
    country = country or wchoice(rng, [(c, v[1]) for c, v in DESTINATIONS.items()])
    method = wchoice(rng, PAYOUT_METHODS)
    ben = Beneficiary(
        beneficiary_id=gen_id(rng, "ben"),
        first_name=rng.choice(FIRST_NAMES),
        last_name=last_name or rng.choice(LAST_NAMES),
        country=country,
        payout_method=method,
        account_last4=None if method == "cash_pickup" else f"{rng.randrange(10000):04d}",
    )
    if rng.random() < 0.08:
        ben.change_at = rand_ts(rng, START + timedelta(days=60), END - timedelta(days=30))
        ben.new_payout_method = wchoice(rng, [(m, w) for m, w in PAYOUT_METHODS if m != method] + [(method, 25)])
        ben.new_account_last4 = None if ben.new_payout_method == "cash_pickup" else f"{rng.randrange(10000):04d}"
    return ben


def build_users(rng: random.Random, n_users: int) -> list[User]:
    users: list[User] = []
    persona_pairs = [(p, v[0]) for p, v in PERSONAS.items()]
    signup_lo = datetime(2024, 1, 1, tzinfo=UTC)
    for _ in range(n_users):
        fn, ln = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        frac = rng.random() ** 0.6
        signup = signup_lo + timedelta(seconds=frac * (END - timedelta(days=10) - signup_lo).total_seconds())
        email_local = f"{fn}.{ln}{rng.randrange(1, 999)}".lower()
        for a, b in zip("áéíóúñ", "aeioun"):
            email_local = email_local.replace(a, b)
        users.append(User(
            user_id=gen_id(rng, "usr"), first_name=fn, last_name=ln,
            email=f"{email_local}@{rng.choice(EMAIL_DOMAINS)}",
            phone=f"+1{rng.randrange(201, 989)}{rng.randrange(2000000, 9999999)}",
            state=wchoice(rng, US_STATES), signup_at=signup,
            kyc_status=wchoice(rng, [("approved", 90), ("pending", 6), ("rejected", 4)]),
            persona=wchoice(rng, persona_pairs),
            pay_pref=wchoice(rng, [("card_only", 58), ("cash_only", 30), ("mixed", 12)]),
            bank=wchoice(rng, [(b, v[0]) for b, v in ISSUING_BANKS.items()]),
            card_last4=f"{rng.randrange(10000):04d}",
            stores=[wchoice(rng, [(s, v[0]) for s, v in RETAILERS.items()]) for _ in range(2)],
        ))
        # heavy senders lean to card (cash limit), one-timers lean to cash
        u = users[-1]
        if u.persona == "heavy" and u.pay_pref == "cash_only" and rng.random() < 0.7:
            u.pay_pref = "mixed"

    for u in users:
        k = wchoice(rng, [(1, 60), (2, 30), (3, 10)])
        home = wchoice(rng, [(c, v[1]) for c, v in DESTINATIONS.items()])
        u.beneficiaries = [make_beneficiary(rng, u.last_name if rng.random() < 0.7 else None, home)
                           for _ in range(k)]

    active = [u for u in users if u.persona != "inactive" and u.kyc_status == "approved"]
    pool = active[:]
    rng.shuffle(pool)
    i = 0
    while i < int(len(pool) * 0.18):          # households sharing one beneficiary
        size = wchoice(rng, [(2, 60), (3, 30), (4, 10)])
        group = pool[i:i + size]
        i += size
        shared = make_beneficiary(rng, group[0].last_name, group[0].beneficiaries[0].country)
        for g in group:
            g.beneficiaries.insert(0, shared)

    card_users = [u for u in active if u.pay_pref != "cash_only"]
    for _ in range(2):                        # mule beneficiaries (card-funded -> chargebacks)
        mule = make_beneficiary(rng, None, "MX")
        mule.payout_method, mule.account_last4, mule.change_at = "bank_deposit", f"{rng.randrange(10000):04d}", None
        for s in rng.sample(card_users, rng.randint(12, 18)):
            s.beneficiaries.append(mule)
            s.is_mule_sender = True
    return users


def schedule(rng: random.Random, u: User) -> list[datetime]:
    lo = max(u.signup_at + timedelta(hours=1), START)
    if lo >= END or u.persona == "inactive" or u.kyc_status != "approved":
        return []
    if u.persona == "one_time":
        dates = [rand_ts(rng, lo, min(lo + timedelta(days=120), END))]
    elif u.persona == "occasional":
        dates = [rand_ts(rng, lo, END) for _ in range(rng.randint(2, 5))]
    else:
        gap_mean, gap_sd = (30, 6) if u.persona == "monthly" else (14, 4)
        churn_p = 0.06 if u.persona == "monthly" else 0.03
        t = rand_ts(rng, lo, min(lo + timedelta(days=gap_mean), END))
        dates = []
        while t <= END:
            dates.append(t)
            if rng.random() < churn_p:
                break
            t = t + timedelta(days=max(3, rng.gauss(gap_mean, gap_sd)), hours=rng.uniform(-12, 12))
    seasonal = [(y, 12, 10, 24, 0.18) for y in (2024, 2025)] + [(y, 5, 1, 10, 0.22) for y in (2025, 2026)]
    for yr, mo, d0, d1, p in seasonal:
        a, b = datetime(yr, mo, d0, tzinfo=UTC), datetime(yr, mo, d1, tzinfo=UTC)
        if lo < a and rng.random() < p * (1.3 if u.beneficiaries[0].country == "MX" else 1.0):
            dates.append(rand_ts(rng, a, b))
    if u.is_mule_sender:
        burst = rand_ts(rng, max(lo, START + timedelta(days=500)), BASELINE_END - timedelta(days=20))
        dates += [burst + timedelta(days=rng.uniform(0, 14)) for _ in range(rng.randint(2, 4))]
    return sorted(d for d in dates if d <= END)


# --------------------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------------------
def generate(n_users: int, seed: int) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    users = build_users(rng, n_users)
    user_rows, pay_rows, rcp_rows, dis_rows = [], [], [], []

    # ---------------- users (CDC versions) ----------------
    for u in users:
        email = u.email.title() if rng.random() < DATA_QUALITY["email_casing_rate"] else u.email
        base = {
            "user_id": u.user_id, "first_name": u.first_name, "last_name": u.last_name,
            "email": email, "phone_number": u.phone, "country": "US", "state": u.state,
            "kyc_status": u.kyc_status if u.kyc_status != "approved" or rng.random() < 0.6 else "pending",
            "created_at": fmt_ts(rng, u.signup_at), "updated_at": fmt_ts(rng, u.signup_at),
        }
        user_rows.append(base)
        if base["kyc_status"] != u.kyc_status:
            upd = u.signup_at + timedelta(hours=rng.uniform(0.2, 72))
            user_rows.append({**base, "kyc_status": u.kyc_status, "updated_at": fmt_ts(rng, upd)})
        if rng.random() < 0.08:
            upd = min(u.signup_at + timedelta(days=rng.uniform(5, 300)), END)
            user_rows.append({**user_rows[-1], "state": wchoice(rng, US_STATES),
                              "kyc_status": u.kyc_status, "updated_at": fmt_ts(rng, upd)})

    # ---------------- payments -> receipts -> disbursements ----------------
    first_done: set[str] = set()
    for u in users:
        for ts in schedule(rng, u):
            to_mule = u.is_mule_sender and ts >= START + timedelta(days=500) and rng.random() < 0.6
            ben = u.beneficiaries[-1] if to_mule else (
                u.beneficiaries[0] if rng.random() < 0.75 else rng.choice(u.beneficiaries))

            # pay-in instrument
            if to_mule or u.pay_pref == "card_only":
                method = "debit_card"
            elif u.pay_pref == "cash_only":
                method = "cash"
            else:
                method = "debit_card" if rng.random() < 0.6 else "cash"
            if method == "debit_card":
                processor = wchoice(rng, [(p, v[0]) for p, v in CARD_PROCESSORS.items()])
                institution, inst_type, card_last4 = u.bank, BANK_TYPE[u.bank], u.card_last4
            else:
                processor = wchoice(rng, [(p, v[0]) for p, v in CASH_NETWORKS.items()])
                institution = rng.choice(u.stores) if rng.random() < 0.9 else wchoice(
                    rng, [(s, v[0]) for s, v in RETAILERS.items()])
                inst_type, card_last4 = "retailer", ""

            mean, sigma = PERSONAS[u.persona][1:]
            if ts.month == 5 and ts.day <= 10:
                mean *= 1.15
            amount = lognormal_amount(rng, mean, sigma, CASH_MAX_USD if method == "cash" else CARD_MAX_USD)
            payout_method, _last4 = ben.as_of(ts)
            first = u.user_id not in first_done
            fee = 0.00 if first else FEE_BY_PAYOUT[payout_method]
            store_fee = STORE_FEE_USD if method == "cash" else 0.0

            payment_id = gen_id(rng, "pay")
            pay_base = {
                "payment_id": payment_id, "user_id": u.user_id, "amount": fmt_amount(rng, amount),
                "fee_amount": f"{fee:.2f}", "store_fee_amount": f"{store_fee:.2f}", "currency": "USD",
                "payment_method": method, "payment_processor": processor,
                "funding_institution": institution, "funding_institution_type": inst_type,
                "card_last4": card_last4, "status": None, "failure_reason": "",
                "created_at": fmt_ts(rng, ts), "updated_at": None,
            }
            # pending version: always for cash (barcode issued), often for cards
            if method == "cash" or rng.random() < 0.6:
                pay_rows.append({**pay_base, "status": messy_status(rng, "pending"),
                                 "updated_at": pay_base["created_at"]})

            if method == "debit_card":
                settled_at = ts + timedelta(seconds=rng.uniform(2, 90))
                fail_p = (CARD_PROCESSORS[processor][1] + (0.04 if first else 0)) * ISSUING_BANKS[u.bank][1]
                if rng.random() < fail_p:
                    pay_rows.append({**pay_base, "status": messy_status(rng, "failed"),
                                     "failure_reason": wchoice(rng, CARD_FAILURE_REASONS),
                                     "updated_at": fmt_ts(rng, settled_at)})
                    continue
            else:
                settled_at = ts + timedelta(minutes=rng.uniform(15, 60 * 30))  # customer walks to the store
                if rng.random() < CASH_EXPIRY_P * RETAILERS[institution][1] * (1.3 if first else 1.0):
                    pay_rows.append({**pay_base, "status": messy_status(rng, "expired"),
                                     "failure_reason": "barcode_not_paid",
                                     "updated_at": fmt_ts(rng, ts + timedelta(hours=48))})
                    continue
            if settled_at > END:
                continue  # still pending at extract end

            first_done.add(u.user_id)
            pay_rows.append({**pay_base, "status": messy_status(rng, "succeeded"),
                             "updated_at": fmt_ts(rng, settled_at)})

            # receipt (FX quote + reference mid-market rate)
            currency = DESTINATIONS[ben.country][0]
            ref = reference_rate(rng, ben.country, settled_at)
            lo_s, hi_s = FX_SPREAD[ben.country]
            rate = round(ref * (1 - rng.uniform(lo_s, hi_s)), 4)
            receive_amount = round(amount * rate, 2)
            receipt_id = gen_id(rng, "rcp")
            rcp_at = settled_at + timedelta(seconds=rng.uniform(1, 20))
            rcp_rows.append({
                "receipt_id": receipt_id, "payment_id": payment_id, "user_id": u.user_id,
                "beneficiary_id": ben.beneficiary_id, "send_amount": fmt_amount(rng, amount),
                "send_currency": "USD", "fx_rate": f"{rate}", "reference_fx_rate": f"{round(ref, 4)}",
                "receive_amount": fmt_amount(rng, receive_amount), "receive_currency": currency,
                "created_at": fmt_ts(rng, rcp_at),
            })

            # disbursement attempts
            routes = ROUTING[ben.country]
            tried: list[str] = []
            attempt_at = rcp_at + timedelta(seconds=rng.uniform(5, 120))
            delivered = False
            for attempt in range(1, 4):
                options = [(p, w) for p, w in routes if p not in tried] or routes
                provider = wchoice(rng, options)
                tried.append(provider)
                pm, l4 = ben.as_of(attempt_at)
                p_fail = PROVIDERS[provider] * (1.5 if pm == "bank_deposit" else 1.0)
                d_base = {
                    "disbursement_id": gen_id(rng, "dsb"), "receipt_id": receipt_id, "attempt_number": attempt,
                    "provider_name": provider, "payout_method": pm, "beneficiary_id": ben.beneficiary_id,
                    "beneficiary_name": f"{ben.first_name} {ben.last_name}", "beneficiary_country": ben.country,
                    "beneficiary_account_last4": l4 or "", "amount": fmt_amount(rng, receive_amount),
                    "currency": currency, "status": None, "failure_reason": "",
                    "created_at": fmt_ts(rng, attempt_at), "updated_at": None,
                }
                dis_rows.append({**d_base, "status": messy_status(rng, "processing"),
                                 "updated_at": d_base["created_at"]})
                done_at = attempt_at + timedelta(minutes=rng.uniform(1, 60 * 18))
                if done_at > END:
                    delivered = True
                    break
                if rng.random() < p_fail:
                    dis_rows.append({**d_base, "status": messy_status(rng, "failed"),
                                     "failure_reason": wchoice(rng, DISB_FAILURE_REASONS),
                                     "updated_at": fmt_ts(rng, done_at)})
                    attempt_at = done_at + timedelta(minutes=rng.uniform(5, 240))
                    continue
                dis_rows.append({**d_base, "status": messy_status(rng, "completed"),
                                 "updated_at": fmt_ts(rng, done_at)})
                delivered = True
                break

            if not delivered:
                ref_at = attempt_at + timedelta(hours=rng.uniform(1, 48))
                if ref_at <= END:
                    pay_rows.append({**pay_base, "status": messy_status(rng, "refunded"),
                                     "failure_reason": "disbursement_failed", "updated_at": fmt_ts(rng, ref_at)})
                continue
            if method == "debit_card":       # chargebacks only exist for cards
                cb_p = (0.009 + (0.004 if first else 0)) * ISSUING_BANKS[u.bank][2]
                if to_mule:
                    cb_p = 0.22
                cb_at = settled_at + timedelta(days=rng.uniform(10, 75))
                if rng.random() < cb_p and cb_at <= END:
                    pay_rows.append({**pay_base, "status": messy_status(rng, "chargeback"),
                                     "failure_reason": wchoice(rng, [("fraudulent", 55), ("unrecognized", 30),
                                                                     ("product_not_received", 15)]),
                                     "updated_at": fmt_ts(rng, cb_at)})
                    continue
            if rng.random() < 0.004:
                ref_at = settled_at + timedelta(hours=rng.uniform(1, 72))
                if ref_at <= END:
                    pay_rows.append({**pay_base, "status": messy_status(rng, "refunded"),
                                     "failure_reason": "customer_request", "updated_at": fmt_ts(rng, ref_at)})

    for _ in range(DATA_QUALITY["orphan_receipts"]):
        src = rng.choice([r for r in rcp_rows if parse_ts(r["created_at"]) <= BASELINE_END])
        rcp_rows.append({**src, "receipt_id": gen_id(rng, "rcp"), "payment_id": gen_id(rng, "pay")})

    def add_dupes(rows):
        rows.extend(dict(r) for r in rng.sample(rows, int(len(rows) * DATA_QUALITY["exact_duplicate_rate"])))
        rows.sort(key=lambda r: parse_ts(r.get("updated_at") or r["created_at"]))
        return rows

    return {"users": add_dupes(user_rows), "payments": add_dupes(pay_rows),
            "receipts": add_dupes(rcp_rows), "disbursements": add_dupes(dis_rows)}


def edge_cases(tables: dict[str, list[dict]], rng: random.Random) -> dict[str, list[dict]]:
    """Hand-crafted bad rows that should trip specific dbt tests (loaded only on demand)."""
    p = next(r for r in tables["payments"] if r["payment_method"] == "debit_card")
    ts = "2026-10-01T12:00:00.000Z"
    rows = [
        {**p, "payment_id": "pay_edge_negative_amount", "amount": "-50.00", "status": "succeeded",
         "created_at": ts, "updated_at": ts},                                  # expression_is_true amount > 0
        {**p, "payment_id": "pay_edge_unknown_method", "payment_method": "zelle", "status": "succeeded",
         "created_at": ts, "updated_at": ts},                                  # accepted_values / unknown member
        {**p, "payment_id": "pay_edge_unknown_status", "status": "on_hold", "created_at": ts, "updated_at": ts},
        {**p, "payment_id": "pay_edge_orphan_user", "user_id": "usr_does_not_exist", "status": "succeeded",
         "created_at": ts, "updated_at": ts},                                  # relationships
        {**p, "payment_id": "pay_edge_cash_chargeback", "payment_method": "cash", "payment_processor": "PayNearMe",
         "funding_institution": "Walmart", "funding_institution_type": "retailer", "card_last4": "",
         "status": "chargeback", "created_at": ts, "updated_at": ts},          # business rule: no cash chargebacks
        {**p, "payment_id": "pay_edge_bad_timestamp", "status": "succeeded",
         "created_at": "01/10/2026 12:00", "updated_at": "01/10/2026 12:00"},  # unparseable timestamp
    ]
    return {"payments": rows}


# --------------------------------------------------------------------------------------
# Writing: baseline (data/source), monthly test batches, edge cases, landing copy
# --------------------------------------------------------------------------------------
def write_csv(path: Path, rows: list[dict], header: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def batch_key(row: dict) -> str:
    ts = parse_ts(row.get("updated_at") or row["created_at"])
    return "baseline" if ts <= BASELINE_END else ts.strftime("%Y-%m")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="data", type=Path)
    ap.add_argument("--users", default=2500, type=int)
    ap.add_argument("--seed", default=42, type=int)
    args = ap.parse_args()

    tables = generate(args.users, args.seed)
    d = args.data_dir
    for sub in ("source", "test_batches", "landing"):
        shutil.rmtree(d / sub, ignore_errors=True)

    summary: dict[str, dict[str, int]] = {}
    for name, rows in tables.items():
        header = list(rows[0].keys())
        buckets: dict[str, list[dict]] = {}
        for r in rows:
            if parse_ts(r.get("updated_at") or r["created_at"]) > END:
                continue  # happens after the simulated extract: not visible yet
            buckets.setdefault(batch_key(r), []).append(r)
        for key, part in sorted(buckets.items()):
            out = d / "source" / f"{name}.csv" if key == "baseline" else d / "test_batches" / key / f"{name}.csv"
            write_csv(out, part, header)
            summary.setdefault(key, {})[name] = len(part)

    for name, rows in edge_cases(tables, random.Random(args.seed)).items():
        write_csv(d / "test_batches" / "edge_cases" / f"{name}.csv", rows, list(rows[0].keys()))

    # landing = working copy the loader reads: one folder per table, one file per batch
    for name in TABLES:
        dst = d / "landing" / name
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(d / "source" / f"{name}.csv", dst / f"{name}__baseline.csv")

    for key in sorted(summary):
        print(f"{key:<10} " + "  ".join(f"{t}={summary[key].get(t, 0):,}" for t in TABLES))
    print(f"landing copy -> {d / 'landing'}")


if __name__ == "__main__":
    main()
