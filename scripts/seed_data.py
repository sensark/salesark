"""Populate the database with realistic test data for demos and analytics.

Usage: python scripts/seed_data.py [--reset] [--orders 1500] [--seed 42]
"""

import argparse
import bisect
import math
import random
import sqlite3
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from faker import Faker  # noqa: E402

from erp.db import engine, init_db, session_scope  # noqa: E402
from erp import config  # noqa: E402
from erp.models import (  # noqa: E402
    REGIONS,
    ROLE_ACCOUNTS,
    ROLE_ADMIN,
    ROLE_SALES,
    ROLE_SALES_MANAGER,
    ROLE_WAREHOUSE,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    Customer,
    CustomerAddress,
    DiscountTier,
    DocumentSeries,
    InventoryMovement,
    Notification,
    Order,
    OrderItem,
    PaymentAllocation,
    Product,
    PriceList,
    PriceListItem,
    TaxRate,
    User,
    Warehouse,
    WarehouseStock,
)
from erp.services.discounts import discount_for, money  # noqa: E402
from erp.services.tax import calculate_gst  # noqa: E402
from erp.services import deliveries, invoices, payments, quotations, returns  # noqa: E402
from erp.services.orders import CartLine  # noqa: E402
from erp.services.users import save_approval_rule  # noqa: E402
from erp.services.accounting_export import seed_default_mappings  # noqa: E402
from erp.services.users import hash_password  # noqa: E402

ADMIN_PASSWORD = "Admin@123"
SALES_PASSWORD = "Sales@123"
MANAGER_PASSWORD = "Manager@123"
ACCOUNTS_PASSWORD = "Accounts@123"
WAREHOUSE_PASSWORD = "Warehouse@123"

CITIES = {
    "North": [("Delhi", "Delhi"), ("Gurugram", "Haryana"), ("Ludhiana", "Punjab"), ("Dehradun", "Uttarakhand")],
    "South": [("Chennai", "Tamil Nadu"), ("Bengaluru", "Karnataka"), ("Hyderabad", "Telangana"), ("Kochi", "Kerala")],
    "East": [("Kolkata", "West Bengal"), ("Bhubaneswar", "Odisha"), ("Patna", "Bihar"), ("Guwahati", "Assam")],
    "West": [("Mumbai", "Maharashtra"), ("Pune", "Maharashtra"), ("Ahmedabad", "Gujarat"), ("Jaipur", "Rajasthan")],
    "Central": [("Bhopal", "Madhya Pradesh"), ("Raipur", "Chhattisgarh"), ("Lucknow", "Uttar Pradesh"), ("Indore", "Madhya Pradesh")],
}

CATALOG = {
    "Wheelchairs and Mobility": [
        ("DEMO Folding Wheelchair", 14500, 5, "EA", "DEMO-HSN-8713"),
        ("DEMO Commode Wheelchair", 18900, 5, "EA", "DEMO-HSN-8713"),
        ("DEMO Rollator Walker", 6200, 12, "EA", "DEMO-HSN-9021"),
        ("DEMO Walking Frame", 2800, 12, "EA", "DEMO-HSN-9021"),
        ("DEMO Crutch Pair", 1100, 12, "PAIR", "DEMO-HSN-9021"),
        ("DEMO Hygiene Chair", 4600, 12, "EA", "DEMO-HSN-9402"),
    ],
    "PU Tyres and Wheels": [
        ("DEMO PU Wheel 125 mm", 780, 18, "EA", "DEMO-HSN-8716"),
        ("DEMO PU Tyre 200 mm", 1250, 18, "EA", "DEMO-HSN-8716"),
        ("DEMO Solid Wheelchair Tyre", 980, 18, "EA", "DEMO-HSN-8714"),
        ("DEMO Castor Assembly", 1650, 18, "EA", "DEMO-HSN-8716"),
        ("DEMO Foam Filled Tyre", 2400, 18, "EA", "DEMO-HSN-4012"),
        ("DEMO Moulded PU Component", 420, 18, "EA", "DEMO-HSN-3926"),
    ],
    "Rehab Components": [
        ("DEMO Wheelchair Armrest Set", 1750, 18, "PAIR", "DEMO-HSN-8714"),
        ("DEMO Wheelchair Fork", 920, 18, "EA", "DEMO-HSN-8714"),
        ("DEMO Seat Cushion", 2100, 12, "EA", "DEMO-HSN-9404"),
        ("DEMO Backrest Assembly", 3400, 18, "EA", "DEMO-HSN-8714"),
        ("DEMO Aluminium Castor Wheel", 1350, 18, "EA", "DEMO-HSN-8716"),
        ("DEMO Rollator Handle Pair", 890, 18, "PAIR", "DEMO-HSN-8714"),
    ],
    "Bicycle Tyres and Wheels": [
        ("DEMO Puncture-Resistant Cycle Tyre", 1150, 18, "EA", "DEMO-HSN-4011"),
        ("DEMO Cycle PU Tyre", 780, 18, "EA", "DEMO-HSN-4011"),
        ("DEMO Bicycle Wheel 26 inch", 2450, 18, "EA", "DEMO-HSN-8714"),
        ("DEMO Cycle Tube", 280, 18, "EA", "DEMO-HSN-4013"),
        ("DEMO Cycle Wheel Set", 4300, 18, "PAIR", "DEMO-HSN-8714"),
        ("DEMO Tyre and Rim Assembly", 1850, 18, "EA", "DEMO-HSN-8714"),
    ],
    "Industrial and Farm Wheels": [
        ("DEMO Industrial PU Wheel", 3400, 18, "EA", "DEMO-HSN-8716"),
        ("DEMO Farm Equipment Wheel", 5600, 18, "EA", "DEMO-HSN-8432"),
        ("DEMO Trolley Wheel 250 mm", 1950, 18, "EA", "DEMO-HSN-8716"),
        ("DEMO Heavy-Duty Castor", 4200, 18, "EA", "DEMO-HSN-8716"),
        ("DEMO Agricultural Tyre", 7800, 18, "EA", "DEMO-HSN-4011"),
        ("DEMO Industrial Wheel Hub", 2650, 18, "EA", "DEMO-HSN-8716"),
    ],
    "Hygiene and Care Aids": [
        ("DEMO Shower Chair", 3600, 12, "EA", "DEMO-HSN-9402"),
        ("DEMO Raised Toilet Seat", 1850, 12, "EA", "DEMO-HSN-3922"),
        ("DEMO Bedside Commode", 4100, 12, "EA", "DEMO-HSN-9402"),
        ("DEMO Transfer Bench", 5200, 12, "EA", "DEMO-HSN-9402"),
        ("DEMO Walking Stick", 650, 12, "EA", "DEMO-HSN-6602"),
        ("DEMO Forearm Crutch", 1450, 12, "EA", "DEMO-HSN-9021"),
    ],
}

# Cheaper items get deeper, higher-quantity tiers; big-ticket items get shallow ones.
TIERS_BY_PRICE = [
    (1500, [(10, 5), (25, 8), (50, 10)]),
    (5000, [(5, 4), (15, 7), (30, 10)]),
    (25_000, [(3, 4), (8, 7), (15, 10)]),
]

SALES_TEAM = [
    ("rahul.sharma", "Rahul Sharma", 1.35),
    ("ananya.iyer", "Ananya Iyer", 1.15),
    ("vikram.singh", "Vikram Singh", 1.0),
    ("sneha.banerjee", "Sneha Banerjee", 0.85),
    ("arjun.nair", "Arjun Nair", 0.65),
]


def tiers_for(price: int) -> list[tuple[int, int]]:
    return next(t for limit, t in TIERS_BY_PRICE if price <= limit)


def pick_qty(rng: random.Random, tiers: list[DiscountTier]) -> int:
    # Cluster quantities around tier thresholds so discount analytics look realistic.
    r = rng.random()
    if r < 0.35 or not tiers:
        return rng.randint(1, max(2, tiers[0].min_qty - 1) if tiers else 6)
    tier = rng.choice(tiers)
    return max(1, tier.min_qty + rng.randint(-2, 4))


def seasonal_weight(day: datetime, start: datetime) -> float:
    months = (day - start).days / 30.4
    growth = 1 + months * 0.025
    season = 1 + 0.25 * math.sin((day.month - 3) / 12 * 2 * math.pi)
    weekday = 0.35 if day.weekday() >= 5 else 1.0
    return growth * season * weekday


def seed(n_orders: int, reset: bool, seed_value: int) -> None:
    rng = random.Random(seed_value)
    fake = Faker("en_IN")
    Faker.seed(seed_value)

    if reset:
        if not engine.url.drivername.startswith("sqlite"):
            raise RuntimeError("The demo reset routine is only supported for SQLite.")
        database = engine.url.database
        connection = sqlite3.connect(database)
        connection.execute("PRAGMA foreign_keys=OFF")
        table_names = [
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table_name in table_names:
            connection.execute(f'DROP TABLE IF EXISTS "{table_name.replace(chr(34), chr(34) * 2)}"')
        connection.commit()
        connection.close()
    init_db()

    with session_scope() as s:
        if s.query(User).count():
            print("Database already contains data. Re-run with --reset to recreate it.")
            return

        admin = User(username="admin", name="Amit Agarwal", email="admin@example.com",
                     password_hash=hash_password(ADMIN_PASSWORD), role=ROLE_ADMIN)
        admin2 = User(username="neha.kapoor", name="Neha Kapoor", email="neha.kapoor@example.com",
                      password_hash=hash_password(ADMIN_PASSWORD), role=ROLE_ADMIN)
        manager = User(username="sales.manager", name="Suresh Menon", email="manager@example.com",
                       password_hash=hash_password(MANAGER_PASSWORD), role=ROLE_SALES_MANAGER)
        accounts = User(username="accounts.demo", name="Kavita Deshpande", email="accounts@example.com",
                        password_hash=hash_password(ACCOUNTS_PASSWORD), role=ROLE_ACCOUNTS)
        warehouse_user = User(username="warehouse.demo", name="Ramesh Yadav", email="warehouse@example.com",
                              password_hash=hash_password(WAREHOUSE_PASSWORD), role=ROLE_WAREHOUSE)
        s.add_all([admin, admin2, manager, accounts, warehouse_user])
        sales_hash = hash_password(SALES_PASSWORD)
        team = []
        for username, name, weight in SALES_TEAM:
            u = User(username=username, name=name, email=f"{username}@example.com",
                     password_hash=sales_hash, role=ROLE_SALES,
                     monthly_target=Decimal(rng.choice([500000, 750000, 1000000])))
            s.add(u)
            team.append((u, weight))
        s.flush()

        products: list[Product] = []
        for ci, (category, items) in enumerate(CATALOG.items()):
            for pi, (pname, price, gst, unit, hsn) in enumerate(items):
                p = Product(
                    sku=f"DEMO-KR-{ci + 1:02d}-{pi + 1:03d}",
                    name=pname,
                    category=category,
                    unit_price=Decimal(price),
                    stock=0,
                    reorder_level=rng.choice([8, 12, 20]),
                    unit=unit,
                    hsn_sac=hsn,
                    tax_category=f"DEMO_GST_{gst}",
                    gst_rate=Decimal(gst),
                )
                p.tiers = [DiscountTier(min_qty=q, discount_pct=Decimal(d)) for q, d in tiers_for(price)]
                products.append(p)
        s.add_all(products)
        s.flush()
        popularity = [rng.uniform(0.4, 2.2) for _ in products]

        for rate in (0, 5, 12, 18, 28):
            s.add(TaxRate(code=f"DEMO-GST-{rate}", name=f"Demo GST {rate}%", gst_rate=Decimal(rate)))
        wholesale = PriceList(name="DEMO Domestic Dealer", currency="INR", active=True)
        retail = PriceList(name="DEMO Domestic Retail", currency="INR", active=True)
        s.add_all([wholesale, retail])
        s.flush()
        for product in products:
            s.add(PriceListItem(price_list_id=wholesale.id, product_id=product.id,
                                unit_price=money(product.unit_price * Decimal("0.94"))))
            s.add(PriceListItem(price_list_id=retail.id, product_id=product.id,
                                unit_price=product.unit_price))

        now = datetime.now().replace(microsecond=0)
        start = now - timedelta(days=548)

        customers: list[Customer] = []
        emails_used: set[str] = set()
        for _ in range(64):
            region = rng.choices(REGIONS, weights=[1.2, 1.0, 1.4, 1.3, 0.7])[0]
            city, state = rng.choice(CITIES[region])
            first, last = fake.first_name(), fake.last_name()
            company = f"DEMO {fake.company()}" if rng.random() < 0.9 else None
            email = f"{first}.{last}".lower().replace("'", "")
            while email in emails_used:
                email += str(rng.randint(1, 9))
            emails_used.add(email)
            address = fake.street_address()
            customer = Customer(
                name=f"DEMO {first} {last}",
                company=company,
                email=f"{email}@example.com",
                phone=fake.numerify("+91-##########"),
                region=region,
                city=city,
                address=address,
                customer_type="BUSINESS" if company else "INDIVIDUAL",
                customer_status="ACTIVE",
                contact_person=f"{first} {last}",
                gst_registration_type="UNREGISTERED",
                state=state,
                place_of_supply_state=state,
                country_code="IN",
                credit_limit=Decimal(rng.choice([0, 250000, 500000, 1000000])),
                credit_period_days=rng.choice([0, 15, 30, 45]),
                price_list_id=wholesale.id if company and rng.random() < 0.65 else retail.id,
                created_by_id=rng.choice(team)[0].id,
                created_at=start + timedelta(days=rng.randint(0, 120)),
            )
            customers.append(customer)
            customer.addresses = [
                CustomerAddress(
                    label="DEMO billing", address_type="BILLING", contact_person=customer.contact_person,
                    phone=customer.phone, line1=address, city=city, state=state,
                    postal_code=fake.postcode(), country="IN", is_default_billing=True,
                ),
                CustomerAddress(
                    label="DEMO shipping", address_type="SHIPPING", contact_person=customer.contact_person,
                    phone=customer.phone, line1=address, city=city, state=state,
                    postal_code=fake.postcode(), country="IN", is_default_shipping=True,
                ),
            ]
        s.add_all(customers)
        s.flush()
        cust_weight = [rng.paretovariate(1.6) for _ in customers]

        # Behaviour profiles give the ML models real signal: churners stop ordering, decliners fade.
        profiles: dict[int, tuple[str, datetime | None]] = {}
        for c in customers:
            r = rng.random()
            if r < 0.22:
                profiles[c.id] = ("churned", start + timedelta(days=rng.randint(200, 500)))
            elif r < 0.37:
                profiles[c.id] = ("declining", None)
            else:
                profiles[c.id] = ("active", None)
        late_payer = {c.id: rng.random() < (0.55 if profiles[c.id][0] != "active" else 0.12) for c in customers}

        def activity(customer_id: int, when: datetime) -> float:
            kind, end = profiles[customer_id]
            if kind == "churned":
                if when >= end:
                    return 0.0
                return 0.35 + 0.65 * min(1.0, (end - when).days / 90)
            if kind == "declining":
                return max(0.15, 1 - 0.85 * (when - start).days / 548)
            return 1.0

        days = [start + timedelta(days=i) for i in range(549)]
        day_weight = [seasonal_weight(d, start) for d in days]
        sold: dict[int, int] = {p.id: 0 for p in products}
        pending_orders: list[Order] = []
        approved_orders: list[Order] = []

        for n in range(n_orders):
            day = rng.choices(days, weights=day_weight)[0]
            created = day.replace(hour=rng.randint(8, 18), minute=rng.randint(0, 59), second=rng.randint(0, 59))
            if created > now:
                created = now - timedelta(minutes=rng.randint(5, 600))
            sp = rng.choices([t[0] for t in team], weights=[t[1] for t in team])[0]
            cust = rng.choices(customers, weights=[w * activity(c.id, day) for c, w in zip(customers, cust_weight)])[0]

            chosen = set()
            for _ in range(rng.choices([1, 2, 3, 4, 5], weights=[30, 30, 20, 12, 8])[0]):
                chosen.add(rng.choices(range(len(products)), weights=popularity)[0])
            items = []
            subtotal = taxable_total = cgst_total = sgst_total = igst_total = cess_total = Decimal("0")
            for idx in chosen:
                p = products[idx]
                qty = pick_qty(rng, p.tiers)
                pct = discount_for(p.tiers, qty)
                tax = calculate_gst(
                    unit_price=p.unit_price, qty=qty, discount_pct=pct,
                    gst_rate=p.gst_rate, cess_rate=p.cess_rate,
                    supplier_state=config.COMPANY_STATE,
                    place_of_supply_state=cust.state or config.COMPANY_STATE,
                )
                items.append(OrderItem(
                    product_id=p.id, qty=qty, unit_price=money(p.unit_price),
                    discount_pct=pct, hsn_sac=p.hsn_sac, gst_rate=p.gst_rate,
                    taxable_amount=tax.taxable, cgst_amount=tax.cgst,
                    sgst_amount=tax.sgst, igst_amount=tax.igst, cess_amount=tax.cess,
                    line_total=tax.taxable,
                ))
                subtotal += tax.gross
                taxable_total += tax.taxable
                cgst_total += tax.cgst
                sgst_total += tax.sgst
                igst_total += tax.igst
                cess_total += tax.cess
            tax_total = cgst_total + sgst_total + igst_total + cess_total
            order_total = taxable_total + tax_total

            age_days = (now - created).days
            if age_days <= 7 and rng.random() < 0.8:
                status = STATUS_PENDING
            else:
                status = STATUS_REJECTED if rng.random() < 0.09 else STATUS_APPROVED
            decided_at = None
            if status != STATUS_PENDING:
                decided_at = min(now, created + timedelta(hours=rng.expovariate(1 / 9) + 0.2))

            order = Order(
                order_no=f"SO-{created:%y%m%d}-{n:05d}", customer_id=cust.id, sales_person_id=sp.id,
                status=status, subtotal=money(subtotal), discount_total=money(subtotal - taxable_total),
                taxable_total=money(taxable_total), cgst_total=money(cgst_total),
                sgst_total=money(sgst_total), igst_total=money(igst_total),
                cess_total=money(cess_total), tax_total=money(tax_total), total=money(order_total),
                currency="INR", billing_address_snapshot=cust.address,
                shipping_address_snapshot=cust.address,
                credit_limit_exceeded=bool(cust.credit_limit and order_total > cust.credit_limit),
                created_at=created, decided_at=decided_at,
                decided_by_id=rng.choice([admin.id, admin2.id]) if decided_at else None,
                rejection_reason=rng.choice([
                    "Customer credit limit exceeded.", "Pricing needs review.",
                    "Duplicate order.", "Customer requested cancellation.",
                ]) if status == STATUS_REJECTED else None,
                notes=rng.choice([None, None, None, "Urgent delivery requested.", "Repeat order.",
                                  "Customer asked for split shipment."]),
                items=items,
            )
            s.add(order)
            if status == STATUS_APPROVED:
                approved_orders.append(order)
                for it in items:
                    sold[it.product_id] += it.qty
            if status == STATUS_PENDING:
                pending_orders.append(order)
        s.flush()

        # Current stock: most products comfortable, a few low or nearly out to exercise warnings.
        low_ids = set(rng.sample([p.id for p in products], 5))
        warehouse = Warehouse(code="KOLKATA", name="DEMO Kolkata Main Warehouse", state="West Bengal")
        s.add(warehouse)
        s.flush()
        for p in products:
            if p.id in low_ids:
                p.stock = rng.randint(0, p.reorder_level)
            else:
                p.stock = rng.randint(120, 600)
            opening_qty = p.stock + sold[p.id]
            s.add(WarehouseStock(warehouse_id=warehouse.id, product_id=p.id, on_hand=p.stock, reserved=0))
            s.add(InventoryMovement(
                product_id=p.id, warehouse_id=warehouse.id, source_type="OPENING",
                source_id=p.id, source_line_id=p.id, qty_delta=opening_qty,
                reason="DEMO opening stock balance", actor_id=admin.id, occurred_at=now,
            ))
        for order in approved_orders:
            for item in order.items:
                s.add(InventoryMovement(
                    product_id=item.product_id, warehouse_id=warehouse.id,
                    source_type="ORDER_APPROVAL", source_id=order.id, source_line_id=item.id,
                    qty_delta=-item.qty, reason="DEMO order approval stock movement",
                    actor_id=order.decided_by_id or admin.id, occurred_at=order.decided_at or order.created_at,
                ))

        for o in pending_orders:
            cust = s.get(Customer, o.customer_id)
            approvers = (admin, admin2, manager)
            if o.required_approver_role == ROLE_ADMIN:
                approvers = (admin, admin2)
            for approver in approvers:
                s.add(Notification(
                    user_id=approver.id, order_id=o.id, created_at=o.created_at,
                    message=f"New order {o.order_no} from {cust.name} ({o.total:,.2f}) awaits approval.",
                ))

        s.add_all([
            DocumentSeries(document_type="ORDER", prefix="SO", next_number=n_orders + 1),
            DocumentSeries(document_type="QUOTATION", prefix="QT"),
            DocumentSeries(document_type="DELIVERY", prefix="DN"),
            DocumentSeries(document_type="INVOICE", prefix="INV"),
            DocumentSeries(document_type="CREDIT_NOTE", prefix="CN"),
            DocumentSeries(document_type="DEBIT_NOTE", prefix="DBN"),
            DocumentSeries(document_type="PAYMENT", prefix="RCPT"),
            DocumentSeries(document_type="RETURN", prefix="SR"),
        ])
        save_approval_rule(
            s, actor_id=admin.id, name="DEMO large order approval", rule_type="ORDER_VALUE",
            threshold=Decimal("1000000"), approver_role=ROLE_ADMIN,
        )
        save_approval_rule(
            s, actor_id=admin.id, name="DEMO high discount approval", rule_type="DISCOUNT_PCT",
            threshold=Decimal("12"), approver_role=ROLE_ADMIN,
        )
        seed_default_mappings(s, accounts.id)

        invoice_batch = []
        settled_orders = [o for o in approved_orders if (now - o.decided_at).days > 3]
        invoiceable = sorted(rng.sample(settled_orders, min(320, len(settled_orders))), key=lambda o: o.created_at)
        for index, order in enumerate(invoiceable):
            invoice_date = min(now, order.decided_at + timedelta(days=rng.randint(1, 4)))
            delivery = deliveries.create_delivery(
                s, order_id=order.id, actor_id=warehouse_user.id,
                quantities={item.id: item.qty for item in order.items},
                transport_name="DEMO Regional Transport",
                tracking_number=f"DEMO-DN-{index + 1:05d}",
            )
            deliveries.confirm_delivery(s, delivery.id, warehouse_user.id, receiver_name="DEMO Goods In",
                                        confirmed_at=invoice_date)
            delivery.created_at = invoice_date
            delivery_items = list(delivery.items)
            invoice = invoices.create_invoice(
                s, delivery_id=delivery.id, actor_id=accounts.id,
                quantities={item.id: item.qty for item in delivery_items}, invoice_date=invoice_date,
            )
            invoices.issue_invoice(s, invoice.id, accounts.id)
            invoice.issued_at = invoice.created_at = invoice_date
            invoice_batch.append(invoice)

            if late_payer[invoice.customer_id]:
                paid_on = invoice.due_date + timedelta(days=rng.randint(12, 75))
            else:
                paid_on = max(invoice_date, invoice.due_date + timedelta(days=rng.randint(-10, 5)))
            partial = rng.random() < 0.1
            if partial:
                paid_on = min(now, invoice_date + timedelta(days=5))
            if paid_on <= now:
                receipt_amount = money(invoice.total / 2) if partial else invoice.total
                payment = payments.create_payment(
                    s, customer_id=invoice.customer_id, actor_id=accounts.id,
                    amount=receipt_amount, method=rng.choice(["UPI", "BANK_TRANSFER", "CHEQUE"]),
                    reference=f"DEMO-REF-{index + 1:05d}",
                )
                payments.allocate_payment(
                    s, payment_id=payment.id, actor_id=accounts.id,
                    allocations={invoice.id: receipt_amount},
                )
                payments.reconcile_payment(s, payment.id, accounts.id)
                payment.payment_date = payment.created_at = paid_on
                for allocation in s.query(PaymentAllocation).filter_by(payment_id=payment.id):
                    allocation.allocated_at = paid_on

            return_rate = 0.04 if profiles[invoice.customer_id][0] == "active" else 0.18
            if invoice.items and rng.random() < return_rate:
                sales_return = returns.create_return(
                    s, invoice_id=invoice.id, actor_id=order.sales_person_id,
                    quantities={invoice.items[0].id: 1}, reason="DAMAGED",
                    notes="DEMO return record",
                )
                returns.decide_return(s, sales_return.id, manager.id, approve=True)
                returns.receive_return(s, sales_return.id, warehouse_user.id)
                credit_note = returns.create_credit_note(s, sales_return.id, accounts.id)
                returns.issue_credit_note(s, credit_note.id, accounts.id)
                sales_return.created_at = min(now, invoice_date + timedelta(days=rng.randint(3, 20)))

        order_dates: dict[int, list[datetime]] = {}
        for order in sorted(approved_orders, key=lambda o: o.created_at):
            order_dates.setdefault(order.customer_id, []).append(order.created_at)
        converted = 0
        backdate: list[tuple] = []
        quote_days = sorted(rng.choices(days[45:], k=150) + rng.choices(days[-12:], k=25))
        for index, qday in enumerate(quote_days):
            created = min(now - timedelta(hours=1), qday.replace(hour=rng.randint(9, 18), minute=rng.randint(0, 59)))
            sales_user = rng.choice(team)[0]
            eligible = [c for c in customers if activity(c.id, created) > 0]
            customer = rng.choice(eligible if eligible and rng.random() > 0.15 else customers)
            product = rng.choices(products, weights=popularity)[0]
            valid_days = rng.choice([14, 30, 45])
            quote = quotations.create_quotation(
                s, customer_id=customer.id, sales_person_id=sales_user.id,
                lines=[CartLine(product.id, pick_qty(rng, product.tiers))],
                valid_days=valid_days, notes="DEMO sample quotation",
                terms="DEMO terms; replace with approved commercial terms.",
            )
            quotations.transition(s, quote.id, sales_user.id, "submit")
            age = (now - created).days
            decide_after = rng.randint(2, 20)
            discount = float(quote.discount_total / quote.subtotal * 100) if quote.subtotal else 0.0
            loyalty = min(1.0, math.log1p(bisect.bisect_left(order_dates.get(customer.id, []), created)) / math.log1p(60))
            z = (-2.2 + 0.35 * discount + 2.5 * loyalty - 0.7 * math.log(max(float(quote.total), 1) / 40000)
                 - (2.0 if activity(customer.id, created) == 0 else 0))
            won = rng.random() < 1 / (1 + math.exp(-z))
            backdate.append((quote, created, valid_days))
            if age < min(valid_days, decide_after):
                stage = rng.choice(["SUBMITTED", "APPROVED", "SENT"])
                if stage != "SUBMITTED":
                    quotations.transition(s, quote.id, manager.id, "approve")
                    quote.decided_at = created + timedelta(hours=rng.randint(2, 30))
                if stage == "SENT":
                    quotations.transition(s, quote.id, sales_user.id, "send")
                    quote.sent_at = quote.decided_at
                continue
            quotations.transition(s, quote.id, manager.id, "approve")
            quotations.transition(s, quote.id, sales_user.id, "send")
            quote.decided_at = quote.sent_at = created + timedelta(hours=rng.randint(2, 30))
            if won:
                quotations.transition(s, quote.id, sales_user.id, "accept")
                quote.accepted_at = min(now, created + timedelta(days=decide_after))
                if age <= 20 and converted < 5:
                    quotations.convert_to_order(s, quote.id, manager.id)
                    converted += 1
            elif age <= valid_days or rng.random() < 0.5:
                quotations.transition(s, quote.id, manager.id, "reject", reason="DEMO customer chose another supplier")
                quote.decided_at = min(now, created + timedelta(days=decide_after))
        # Workflow rejects expired quotes, so historical dates are applied after all transitions.
        for quote, created, valid_days in backdate:
            quote.created_at = created
            quote.valid_until = created + timedelta(days=valid_days)
        s.flush()
        quotations.expire_due(s, now)

        print(f"Seeded {len(team)} sales people, 2 admins, 1 manager, 1 accounts user, "
              f"1 warehouse user, {len(customers)} DEMO customers, "
              f"{len(products)} products, {n_orders} orders ({len(pending_orders)} pending).")
        print("\nLogins:")
        print(f"  admin / {ADMIN_PASSWORD}   (Admin / Owner)")
        print(f"  sales.manager / {MANAGER_PASSWORD}   (Sales Manager)")
        print(f"  accounts.demo / {ACCOUNTS_PASSWORD}   (Accounts)")
        print(f"  warehouse.demo / {WAREHOUSE_PASSWORD}   (Warehouse)")
        for username, _, _ in SALES_TEAM:
            print(f"  {username} / {SALES_PASSWORD}   (Sales Person)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the Sales ERP database with test data.")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables first")
    parser.add_argument("--orders", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    seed(args.orders, args.reset, args.seed)
