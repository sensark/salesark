
import pytest

from erp.models import ROLE_SALES_MANAGER, User
from erp.services import customers
from erp.services.customers import CustomerError
from erp.services.orders import CartLine, OrderError, place_order


def test_create_customer_with_indian_tax_and_addresses(session, data):
    customer = customers.create(
        session, name="Sample Dealer", email="dealer@example.com", region="East",
        created_by_id=data["sales"].id, company="Sample Mobility Dealer",
        state="West Bengal", gst_registration_type="REGULAR",
        gstin="19ABCDE1234F1Z5", pan="ABCDE1234F",
        billing_line1="1 Demo Road", billing_city="Kolkata", billing_state="West Bengal",
        billing_postal_code="700001", shipping_line1="2 Demo Road",
        shipping_city="Kolkata", shipping_state="West Bengal", shipping_postal_code="700002",
    )
    assert customer.country_code == "IN"
    assert customer.gstin == "19ABCDE1234F1Z5"
    assert len(customer.addresses) == 2
    assert next(a for a in customer.addresses if a.is_default_billing).postal_code == "700001"


def test_customer_rejects_invalid_tax_ids(session, data):
    with pytest.raises(CustomerError):
        customers.create(session, name="Bad GST", email="badgst@example.com", region="East",
                         created_by_id=data["sales"].id, state="West Bengal",
                         gstin="NOT-A-GSTIN", gst_registration_type="REGULAR")
    with pytest.raises(CustomerError):
        customers.create(session, name="Bad PAN", email="badpan@example.com", region="East",
                         created_by_id=data["sales"].id, pan="NOPE")


def test_inactive_customer_cannot_order_and_manager_can_reactivate(session, data):
    manager = User(username="customer_manager", name="Manager", email="cm@example.com",
                   password_hash="x", role=ROLE_SALES_MANAGER)
    session.add(manager)
    session.flush()
    customers.set_status(session, customer_id=data["customer"].id, actor_id=manager.id, status="INACTIVE")
    with pytest.raises(OrderError):
        place_order(session, sales_person_id=data["sales"].id, customer_id=data["customer"].id,
                    lines=[CartLine(data["pen"].id, 1)])
    customers.set_status(session, customer_id=data["customer"].id, actor_id=manager.id, status="ACTIVE")
    assert data["customer"].customer_status == "ACTIVE"
