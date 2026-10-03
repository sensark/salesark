import pytest

from erp.models import ROLE_ADMIN
from erp.services.users import UserError, create_first_admin


def test_first_admin_can_be_created_in_empty_database(session):
    admin = create_first_admin(
        session, username="owner", name="ERP Owner", email="owner@example.com",
        password="SecurePass123",
    )
    assert admin.role == ROLE_ADMIN
    assert admin.password_hash != "SecurePass123"


def test_first_admin_setup_cannot_be_repeated(session, data):
    with pytest.raises(UserError, match="already complete"):
        create_first_admin(
            session, username="second", name="Second Admin", email="second@example.com",
            password="SecurePass123",
        )
