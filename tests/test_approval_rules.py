from decimal import Decimal

import pytest

from erp.models import ROLE_ADMIN, ROLE_SALES_MANAGER
from erp.services import orders
from erp.services.orders import CartLine
from erp.services.users import UserError, save_approval_rule


def test_configured_order_value_rule_requires_admin(session, data):
    save_approval_rule(session, actor_id=data["admin"].id, name="Large deal", rule_type="ORDER_VALUE",
                       threshold=Decimal("200"), approver_role=ROLE_ADMIN)
    order = orders.place_order(session, sales_person_id=data["sales"].id,
                               customer_id=data["customer"].id, lines=[CartLine(data["pen"].id, 25)])
    assert order.required_approver_role == ROLE_ADMIN
    with pytest.raises(orders.OrderError):
        orders.approve_order(session, order.id, data["sales"].id)


def test_manager_rule_keeps_credit_exception_with_manager(session, data):
    data["customer"].credit_limit = Decimal("50")
    save_approval_rule(session, actor_id=data["admin"].id, name="Volume discount",
                       rule_type="DISCOUNT_PCT", threshold=Decimal("5"),
                       approver_role=ROLE_SALES_MANAGER)
    order = orders.place_order(session, sales_person_id=data["sales"].id,
                               customer_id=data["customer"].id, lines=[CartLine(data["pen"].id, 25)])
    assert order.credit_limit_exceeded
    assert order.required_approver_role == ROLE_SALES_MANAGER


def test_rule_threshold_must_be_positive(session, data):
    with pytest.raises(UserError):
        save_approval_rule(session, actor_id=data["admin"].id, name="Invalid",
                           rule_type="ORDER_VALUE", threshold=Decimal("0"),
                           approver_role=ROLE_ADMIN)
