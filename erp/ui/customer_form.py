import streamlit as st
from sqlalchemy import select

from erp.db import session_scope
from erp.models import INDIAN_STATES, PriceList


GST_TYPES = ["UNREGISTERED", "REGULAR", "COMPOSITION", "SEZ", "EXPORT"]
CUSTOMER_TYPES = ["BUSINESS", "INDIVIDUAL", "GOVERNMENT", "OTHER"]


def customer_fields(prefix: str) -> dict:
    col1, col2 = st.columns(2)
    customer_type = col1.selectbox("Customer type", CUSTOMER_TYPES, key=f"{prefix}_type")
    contact_person = col2.text_input("Contact person", key=f"{prefix}_contact")
    country_code = col1.selectbox(
        "Country", ["IN", "US", "GB", "DE", "AU", "AE"],
        format_func=lambda code: {"IN": "India", "US": "United States", "GB": "United Kingdom",
                                  "DE": "Germany", "AU": "Australia", "AE": "United Arab Emirates"}[code],
        key=f"{prefix}_country",
    )
    state_options = ["", *INDIAN_STATES] if country_code == "IN" else ["Outside India"]
    state = col2.selectbox("State / place of supply", state_options, key=f"{prefix}_state")
    registration = col2.selectbox("GST registration", GST_TYPES, key=f"{prefix}_gst_type")
    gstin = col1.text_input("GSTIN", key=f"{prefix}_gstin", max_chars=15)
    pan = col2.text_input("PAN", key=f"{prefix}_pan", max_chars=10)
    credit_limit = col1.number_input("Credit limit (INR, 0 = unset)", min_value=0, step=10000,
                                     key=f"{prefix}_credit_limit")
    credit_days = col2.number_input("Credit period (days)", min_value=0, max_value=365, step=1,
                                    key=f"{prefix}_credit_days")
    with session_scope() as session:
        price_lists = list(session.scalars(
            select(PriceList).where(PriceList.active.is_(True)).order_by(PriceList.name)
        ))
    price_list = col1.selectbox(
        "Price list", [None, *price_lists],
        format_func=lambda item: "Standard product prices" if item is None else item.name,
        key=f"{prefix}_price_list",
    )
    with st.expander("Billing and shipping addresses"):
        st.caption("Leave address fields blank to use the primary address above.")
        b1, b2 = st.columns(2)
        billing_line1 = b1.text_input("Billing address", key=f"{prefix}_bill_line")
        shipping_line1 = b2.text_input("Shipping address", key=f"{prefix}_ship_line")
        b3, b4 = st.columns(2)
        billing_city = b3.text_input("Billing city", key=f"{prefix}_bill_city")
        shipping_city = b4.text_input("Shipping city", key=f"{prefix}_ship_city")
        b5, b6 = st.columns(2)
        billing_state = b5.selectbox("Billing state", ["", *INDIAN_STATES], key=f"{prefix}_bill_state")
        shipping_state = b6.selectbox("Shipping state", ["", *INDIAN_STATES], key=f"{prefix}_ship_state")
        b7, b8 = st.columns(2)
        billing_postal = b7.text_input("Billing PIN code", key=f"{prefix}_bill_pin")
        shipping_postal = b8.text_input("Shipping PIN code", key=f"{prefix}_ship_pin")
        b9, b10 = st.columns(2)
        country_codes = ["IN", "US", "GB", "DE", "AU", "AE"]
        billing_country = b9.selectbox("Billing country", country_codes, key=f"{prefix}_bill_country")
        shipping_country = b10.selectbox("Shipping country", country_codes, key=f"{prefix}_ship_country")
    return {
        "customer_type": customer_type,
        "contact_person": contact_person,
        "state": state,
        "country_code": country_code,
        "gst_registration_type": registration,
        "gstin": gstin,
        "pan": pan,
        "credit_limit": int(credit_limit),
        "credit_period_days": int(credit_days),
        "price_list_id": price_list.id if price_list else None,
        "billing_line1": billing_line1,
        "billing_city": billing_city,
        "billing_state": billing_state,
        "billing_postal_code": billing_postal,
        "billing_country": billing_country,
        "shipping_line1": shipping_line1,
        "shipping_city": shipping_city,
        "shipping_state": shipping_state,
        "shipping_postal_code": shipping_postal,
        "shipping_country": shipping_country,
    }
