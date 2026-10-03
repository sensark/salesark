from erp.models import (
    ROLE_ACCOUNTS,
    ROLE_ADMIN_OWNER,
    ROLE_SALES_EXECUTIVE,
    ROLE_SALES_MANAGER,
    ROLE_WAREHOUSE,
)

ROLE_LABELS = {
    ROLE_ADMIN_OWNER: "Admin / Owner",
    ROLE_SALES_EXECUTIVE: "Sales Executive",
    ROLE_SALES_MANAGER: "Sales Manager",
    ROLE_ACCOUNTS: "Accounts",
    ROLE_WAREHOUSE: "Warehouse",
}

ROLE_ACTIONS: dict[str, frozenset[str]] = {
    ROLE_ADMIN_OWNER: frozenset({"*"}),
    ROLE_SALES_EXECUTIVE: frozenset({
        "customer.read", "customer.create", "quotation.read_own", "quotation.create",
        "quotation.send", "quotation.accept", "quotation.convert", "quotation.cancel",
        "order.read_own", "order.create", "order.submit", "order.cancel", "return.create",
    }),
    ROLE_SALES_MANAGER: frozenset({
        "customer.read", "customer.create", "customer.update", "customer.status", "quotation.read",
        "quotation.create", "quotation.approve", "quotation.send", "quotation.convert",
        "order.read", "order.create", "order.submit", "order.cancel", "order.approve", "order.reject",
        "return.create", "return.approve", "report.sales.read", "analytics.retrain",
    }),
    ROLE_ACCOUNTS: frozenset({
        "customer.read", "invoice.read", "invoice.create", "invoice.issue", "invoice.cancel",
        "payment.read", "payment.create", "payment.allocate", "payment.reconcile",
        "credit_note.read", "credit_note.create", "credit_note.issue", "report.financial.read",
        "return.read", "return.create", "accounting.export",
    }),
    ROLE_WAREHOUSE: frozenset({
        "product.read", "order.read_fulfillment", "delivery.read", "delivery.create",
        "delivery.confirm", "inventory.read", "inventory.adjust",
        "return.receive",
    }),
}


def allows(role: str, action: str) -> bool:
    grants = ROLE_ACTIONS.get(role, frozenset())
    return "*" in grants or action in grants


def require_action(role: str, action: str) -> None:
    if not allows(role, action):
        raise PermissionError(f"Role {ROLE_LABELS.get(role, role)!r} cannot perform {action!r}.")
