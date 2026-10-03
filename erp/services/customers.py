import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from erp.models import Customer, CustomerAddress, INDIAN_STATES, REGIONS, User
from erp.permissions import require_action
from erp.services import audit

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


class CustomerError(ValueError):
    pass


def search(session: Session, term: str = "", limit: int = 50) -> list[Customer]:
    stmt = select(Customer).order_by(Customer.name).limit(limit)
    term = term.strip()
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(Customer.name.ilike(like), Customer.company.ilike(like),
                Customer.email.ilike(like), Customer.phone.ilike(like))
        )
    return list(session.scalars(stmt))


def get_by_email(session: Session, email: str) -> Customer | None:
    return session.scalar(select(Customer).where(func.lower(Customer.email) == email.strip().lower()))


def create(
    session: Session,
    *,
    name: str,
    email: str,
    region: str,
    created_by_id: int,
    company: str = "",
    phone: str = "",
    city: str = "",
    address: str = "",
    customer_type: str = "BUSINESS",
    contact_person: str = "",
    gstin: str = "",
    pan: str = "",
    gst_registration_type: str = "UNREGISTERED",
    state: str = "",
    country_code: str = "IN",
    credit_limit: int = 0,
    credit_period_days: int = 0,
    price_list_id: int | None = None,
    billing_line1: str = "",
    billing_city: str = "",
    billing_state: str = "",
    billing_postal_code: str = "",
    billing_country: str = "IN",
    shipping_line1: str = "",
    shipping_city: str = "",
    shipping_state: str = "",
    shipping_postal_code: str = "",
    shipping_country: str = "IN",
) -> Customer:
    name, email = name.strip(), email.strip().lower()
    if not name:
        raise CustomerError("Customer name is required.")
    if not EMAIL_RE.match(email):
        raise CustomerError("Please enter a valid email address.")
    if region not in REGIONS:
        raise CustomerError("Please select a valid region.")
    if customer_type not in {"BUSINESS", "INDIVIDUAL", "GOVERNMENT", "OTHER"}:
        raise CustomerError("Please select a valid customer type.")
    if gst_registration_type not in {"REGULAR", "COMPOSITION", "UNREGISTERED", "SEZ", "EXPORT"}:
        raise CustomerError("Please select a valid GST registration type.")
    if country_code == "IN" and gstin.strip() and not GSTIN_RE.fullmatch(gstin.strip().upper()):
        raise CustomerError("Enter a valid 15-character GSTIN or leave it blank for demo data.")
    if pan.strip() and not PAN_RE.fullmatch(pan.strip().upper()):
        raise CustomerError("Enter a valid 10-character PAN or leave it blank.")
    country_code = country_code.strip().upper()
    if country_code == "IN" and state and state not in INDIAN_STATES:
        raise CustomerError("Please select a valid Indian state.")
    if credit_limit < 0 or credit_period_days < 0:
        raise CustomerError("Credit limit and credit period cannot be negative.")
    actor = session.get(User, created_by_id)
    if actor is None:
        raise CustomerError("Creating sales user was not found.")
    try:
        require_action(actor.role, "customer.create")
    except PermissionError as exc:
        raise CustomerError(str(exc)) from exc
    existing = get_by_email(session, email)
    if existing:
        raise CustomerError(f"A customer with this email already exists: {existing.name}.")
    customer = Customer(
        name=name, email=email, region=region, created_by_id=created_by_id,
        company=company.strip() or None, phone=phone.strip() or None,
        city=city.strip() or None, address=address.strip() or None,
        customer_type=customer_type,
        contact_person=contact_person.strip() or None,
        gstin=gstin.strip().upper() or None,
        pan=pan.strip().upper() or None,
        gst_registration_type=gst_registration_type,
        state=state.strip() or None,
        country_code=country_code,
        place_of_supply_state=state.strip() or None,
        credit_limit=credit_limit,
        credit_period_days=credit_period_days,
        price_list_id=price_list_id,
    )
    billing_line1 = billing_line1.strip() or address.strip()
    shipping_line1 = shipping_line1.strip() or address.strip() or billing_line1
    billing_city = billing_city.strip() or city.strip()
    shipping_city = shipping_city.strip() or city.strip() or billing_city
    billing_state = billing_state.strip() or state.strip()
    shipping_state = shipping_state.strip() or state.strip() or billing_state
    if billing_line1 and billing_city and billing_state:
        customer.addresses.append(CustomerAddress(
            label="Billing", address_type="BILLING", line1=billing_line1,
            city=billing_city, state=billing_state,
            postal_code=billing_postal_code.strip(), country=billing_country.strip().upper(),
            is_default_billing=True,
        ))
    if shipping_line1 and shipping_city and shipping_state:
        customer.addresses.append(CustomerAddress(
            label="Shipping", address_type="SHIPPING", line1=shipping_line1,
            city=shipping_city, state=shipping_state,
            postal_code=shipping_postal_code.strip(), country=shipping_country.strip().upper(),
            is_default_shipping=True,
        ))
    session.add(customer)
    session.flush()
    audit.record(
        session, actor_id=created_by_id, action="CREATE", entity_type="CUSTOMER",
        entity_id=customer.id, changes={"name": customer.name, "status": customer.customer_status,
                                       "gst_registration_type": customer.gst_registration_type},
    )
    return customer


def set_status(session: Session, *, customer_id: int, actor_id: int, status: str) -> Customer:
    actor = session.get(User, actor_id)
    if actor is None:
        raise CustomerError("User not found.")
    try:
        require_action(actor.role, "customer.status")
    except PermissionError as exc:
        raise CustomerError(str(exc)) from exc
    if status not in {"ACTIVE", "INACTIVE", "ON_HOLD"}:
        raise CustomerError("Invalid customer status.")
    customer = session.get(Customer, customer_id)
    if customer is None:
        raise CustomerError("Customer not found.")
    old_status = customer.customer_status
    customer.customer_status = status
    audit.record(
        session, actor_id=actor.id, action="STATUS", entity_type="CUSTOMER",
        entity_id=customer.id, changes={"from": old_status, "to": status},
    )
    return customer
