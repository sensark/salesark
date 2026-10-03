import pytest

from erp.models import ROLE_ACCOUNTS, ROLE_ADMIN, ROLE_SALES, ROLE_SALES_MANAGER, ROLE_WAREHOUSE
from erp.permissions import allows, require_action


@pytest.mark.parametrize(
    ("role", "action", "expected"),
    [
        (ROLE_ADMIN, "accounting.export", True),
        (ROLE_SALES, "customer.create", True),
        (ROLE_SALES, "order.approve", False),
        (ROLE_SALES_MANAGER, "order.approve", True),
        (ROLE_SALES_MANAGER, "payment.allocate", False),
        (ROLE_ACCOUNTS, "payment.allocate", True),
        (ROLE_ACCOUNTS, "delivery.confirm", False),
        (ROLE_WAREHOUSE, "delivery.confirm", True),
        ("unknown", "customer.read", False),
    ],
)
def test_role_action_matrix(role, action, expected):
    assert allows(role, action) is expected


def test_require_action_rejects_ungranted_action():
    with pytest.raises(PermissionError):
        require_action(ROLE_SALES, "order.approve")
