#!/usr/bin/env python3
"""Streamlit UI for House Hunter investment analysis."""

from __future__ import annotations

import urllib.request
from types import SimpleNamespace
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st

from app import RentEstimator, load_listings, recommend


def secret_value(name: str, default):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default


def secret_float(name: str, default: float) -> float:
    value = secret_value(name, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def secret_int(name: str, default: int) -> int:
    value = secret_value(name, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


@st.cache_data(ttl=60 * 60 * 24)
def fetch_market_rate() -> float | None:
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US"
        with urllib.request.urlopen(url, timeout=15) as response:
            lines = response.read().decode("utf-8").strip().splitlines()
        for row in reversed(lines[1:]):
            parts = row.split(",")
            if len(parts) == 2 and parts[1] != ".":
                return float(parts[1])
    except Exception:
        return None
    return None


def build_args(**kwargs):
    return SimpleNamespace(
        **kwargs,
        rapidapi_key=secret_value("RAPIDAPI_KEY", None),
        config_file=".house_hunter.env",
    )


st.set_page_config(page_title="House Hunter", layout="wide")
st.title("🏠 House Hunter Investment Recommender")
st.caption("Find active listings with projected positive cashflow.")

if "analysis_calls" not in st.session_state:
    st.session_state.analysis_calls = []

col_a, col_b, col_c = st.columns(3)
with col_a:
    location = st.text_input("Location (ZIP, State, or City)", value=str(secret_value("DEFAULT_LOCATION", "76131")))
    max_price = st.number_input("Max Purchase Price", min_value=50000, value=secret_int("DEFAULT_MAX_PRICE", 900000), step=10000)
    max_down_payment = st.number_input("Max Down Payment", min_value=1000, value=secret_int("DEFAULT_MAX_DOWN_PAYMENT", 300000), step=5000)
    min_bedrooms = st.number_input("Min Bedrooms", min_value=0.0, value=0.0, step=0.5)

with col_b:
    interest_rate = st.number_input("Interest Rate (%)", min_value=0.0, value=secret_float("DEFAULT_INTEREST_RATE", 7.25), step=0.05)
    market_rate = fetch_market_rate()
    if market_rate:
        st.caption(f"Freddie/FRED 30Y primary mortgage avg: {market_rate:.2f}% (investment loans often +0.5% to +1.0%).")
        if st.button("Use latest market rate +0.75% investor spread"):
            interest_rate = round(market_rate + 0.75, 2)
    loan_years = st.number_input("Loan Term (years)", min_value=5, value=30, step=5)
    insurance_rate = st.number_input("Base insurance rate (annual pct of price)", min_value=0.0, value=secret_float("DEFAULT_INSURANCE_RATE", 0.0035), step=0.0005, format="%.4f")
    landlord_insurance_multiplier = st.number_input("Landlord insurance multiplier", min_value=1.0, value=1.15, step=0.05)

with col_c:
    maintenance_rate = st.number_input("Maintenance Rate (pct of rent)", min_value=0.0, value=secret_float("DEFAULT_MAINTENANCE_RATE", 0.05), step=0.01)
    management_rate = st.number_input("Management Rate (pct of rent)", min_value=0.0, value=secret_float("DEFAULT_MANAGEMENT_RATE", 0.08), step=0.01, help="Typical PM rates are commonly 8-12% depending on market and service level.")
    vacancy_rate = st.number_input("Vacancy Rate (pct of rent)", min_value=0.0, value=secret_float("DEFAULT_VACANCY_RATE", 0.05), step=0.01, help="Example: 8.3% means ~1 month vacant per year. 4.2% means ~2 weeks.")
    pmi_rate = st.number_input("PMI rate when <20% down (annual)", min_value=0.0, value=0.008, step=0.001, format="%.3f")

property_types = st.multiselect("Property type filter", ["single_family", "condo", "townhome", "multi_family", "apartment"], default=[])
min_bathrooms = st.number_input("Min Bathrooms", min_value=0.0, value=0.0, step=0.5)

st.info("Default mode uses live API listings. Most developer/API settings stay hidden in Advanced.")

with st.expander("Advanced settings", expanded=False):
    st.subheader("Data Source")
    source_default = str(secret_value("DEFAULT_SOURCE", "rapidapi-realtor"))
    source = st.selectbox("Listing Source", ["rapidapi-realtor", "csv"], index=0 if source_default == "rapidapi-realtor" else 1)
    listings_csv = st.text_input("Listings CSV", value="data/listings_sample.csv")
    rental_comps_csv = st.text_input("Rental comps CSV (optional)", value="data/rental_comps_sample.csv")

    st.subheader("Rent Source")
    rent_source_default = str(secret_value("DEFAULT_RENT_SOURCE", "hybrid"))
    rent_options = ["hybrid", "rapidapi-realtor", "csv", "heuristic"]
    rent_source = st.selectbox("Rent Source", rent_options, index=rent_options.index(rent_source_default) if rent_source_default in rent_options else 0)
    results = st.slider("Max recommendations", 1, 25, secret_int("DEFAULT_RESULTS", 5), step=1)
    min_rent_comps = st.slider("Minimum rent comps", 1, 20, secret_int("DEFAULT_MIN_RENT_COMPS", 2))

    with st.expander("Developer/API Config", expanded=False):
        rapidapi_host = st.text_input("RapidAPI Host", value=secret_value("RAPIDAPI_HOST", "realty-in-us.p.rapidapi.com"))
        rapidapi_endpoint = st.text_input("RapidAPI Sale Endpoint", value=secret_value("RAPIDAPI_SALE_ENDPOINT", "/properties/v3/list"))
        rapidapi_method_default = str(secret_value("RAPIDAPI_SALE_METHOD", "POST")).upper()
        rapidapi_method = st.selectbox("RapidAPI Sale Method", ["POST", "GET"], index=0 if rapidapi_method_default == "POST" else 1)
        rapidapi_location_param = st.text_input("RapidAPI Sale Location Param", value=secret_value("RAPIDAPI_SALE_LOCATION_PARAM", "postal_code"))
        rapidapi_rent_endpoint = st.text_input("RapidAPI Rent Endpoint", value=secret_value("RAPIDAPI_RENT_ENDPOINT", "/properties/v3/list"))
        rapidapi_rent_method_default = str(secret_value("RAPIDAPI_RENT_METHOD", "POST")).upper()
        rapidapi_rent_method = st.selectbox("RapidAPI Rent Method", ["POST", "GET"], index=0 if rapidapi_rent_method_default == "POST" else 1)
        rapidapi_rent_location_param = st.text_input("RapidAPI Rent Location Param", value=secret_value("RAPIDAPI_RENT_LOCATION_PARAM", "postal_code"))
        rapidapi_limit = st.slider("Sale API Limit", 20, 200, 100, step=20)
        rapidapi_rent_limit = st.slider("Rent API Limit", 20, 200, 120, step=20)

    st.subheader("Advanced preferences / scoring")
    c1, c2, c3, c4, c5 = st.columns(5)
    target_sqft = c1.number_input("Target Sqft", min_value=500, value=1800, step=50)
    target_bedrooms = c2.number_input("Target Beds", min_value=0.0, value=3.0, step=0.5)
    target_bathrooms = c3.number_input("Target Baths", min_value=0.0, value=2.0, step=0.5)
    target_year_built = c4.number_input("Target Year Built", min_value=1900, value=1995, step=1)
    target_lot_size = c5.number_input("Target Lot Sqft", min_value=0, value=7000, step=100)

    w1, w2, w3, w4, w5 = st.columns(5)
    weight_sqft = w1.number_input("Weight Sqft", min_value=0.0, value=3.0, step=0.5)
    weight_bedrooms = w2.number_input("Weight Beds", min_value=0.0, value=2.0, step=0.5)
    weight_bathrooms = w3.number_input("Weight Baths", min_value=0.0, value=2.0, step=0.5)
    weight_year_built = w4.number_input("Weight Year", min_value=0.0, value=1.5, step=0.5)
    weight_lot_size = w5.number_input("Weight Lot", min_value=0.0, value=1.0, step=0.5)

# defaults if expander never opened
source = locals().get("source", str(secret_value("DEFAULT_SOURCE", "rapidapi-realtor")))
listings_csv = locals().get("listings_csv", "data/listings_sample.csv")
rental_comps_csv = locals().get("rental_comps_csv", "data/rental_comps_sample.csv")
rent_source = locals().get("rent_source", str(secret_value("DEFAULT_RENT_SOURCE", "hybrid")))
results = locals().get("results", secret_int("DEFAULT_RESULTS", 5))
min_rent_comps = locals().get("min_rent_comps", secret_int("DEFAULT_MIN_RENT_COMPS", 2))
rapidapi_host = locals().get("rapidapi_host", secret_value("RAPIDAPI_HOST", "realty-in-us.p.rapidapi.com"))
rapidapi_endpoint = locals().get("rapidapi_endpoint", secret_value("RAPIDAPI_SALE_ENDPOINT", "/properties/v3/list"))
rapidapi_method = locals().get("rapidapi_method", str(secret_value("RAPIDAPI_SALE_METHOD", "POST")).upper())
rapidapi_location_param = locals().get("rapidapi_location_param", secret_value("RAPIDAPI_SALE_LOCATION_PARAM", "postal_code"))
rapidapi_rent_endpoint = locals().get("rapidapi_rent_endpoint", secret_value("RAPIDAPI_RENT_ENDPOINT", "/properties/v3/list"))
rapidapi_rent_method = locals().get("rapidapi_rent_method", str(secret_value("RAPIDAPI_RENT_METHOD", "POST")).upper())
rapidapi_rent_location_param = locals().get("rapidapi_rent_location_param", secret_value("RAPIDAPI_RENT_LOCATION_PARAM", "postal_code"))
rapidapi_limit = locals().get("rapidapi_limit", 100)
rapidapi_rent_limit = locals().get("rapidapi_rent_limit", 120)
target_sqft = locals().get("target_sqft", 1800)
target_bedrooms = locals().get("target_bedrooms", 3.0)
target_bathrooms = locals().get("target_bathrooms", 2.0)
target_year_built = locals().get("target_year_built", 1995)
target_lot_size = locals().get("target_lot_size", 7000)
weight_sqft = locals().get("weight_sqft", 3.0)
weight_bedrooms = locals().get("weight_bedrooms", 2.0)
weight_bathrooms = locals().get("weight_bathrooms", 2.0)
weight_year_built = locals().get("weight_year_built", 1.5)
weight_lot_size = locals().get("weight_lot_size", 1.0)

args = build_args(
    source=source,
    listings_csv=listings_csv,
    location=location,
    max_price=float(max_price),
    max_down_payment=float(max_down_payment),
    interest_rate=float(interest_rate),
    loan_years=int(loan_years),
    target_sqft=float(target_sqft),
    target_bedrooms=float(target_bedrooms),
    target_bathrooms=float(target_bathrooms),
    target_year_built=float(target_year_built),
    target_lot_size=float(target_lot_size),
    weight_sqft=float(weight_sqft),
    weight_bedrooms=float(weight_bedrooms),
    weight_bathrooms=float(weight_bathrooms),
    weight_year_built=float(weight_year_built),
    weight_lot_size=float(weight_lot_size),
    insurance_rate=float(insurance_rate),
    landlord_insurance_multiplier=float(landlord_insurance_multiplier),
    maintenance_rate=float(maintenance_rate),
    management_rate=float(management_rate),
    vacancy_rate=float(vacancy_rate),
    pmi_rate=float(pmi_rate),
    results=int(results),
    rapidapi_host=rapidapi_host,
    rapidapi_endpoint=rapidapi_endpoint,
    rapidapi_limit=int(rapidapi_limit),
    rapidapi_method=rapidapi_method,
    rapidapi_location_param=rapidapi_location_param,
    rent_source=rent_source,
    rental_comps_csv=rental_comps_csv if rental_comps_csv else None,
    rapidapi_rent_endpoint=rapidapi_rent_endpoint,
    rapidapi_rent_limit=int(rapidapi_rent_limit),
    rapidapi_rent_method=rapidapi_rent_method,
    rapidapi_rent_location_param=rapidapi_rent_location_param,
    min_rent_comps=int(min_rent_comps),
    property_types=",".join(property_types),
    min_bedrooms=float(min_bedrooms),
    min_bathrooms=float(min_bathrooms),
)

if st.button("Run analysis", type="primary"):
    now = pd.Timestamp.utcnow().timestamp()
    recent = [t for t in st.session_state.analysis_calls if now - t < 60]
    if len(recent) >= 8:
        st.warning("Rate limit reached: please wait a minute before running another batch.")
        st.stop()
    st.session_state.analysis_calls = recent + [now]

    try:
        listings = load_listings(args)
        estimator = RentEstimator(args)
        recommendations = recommend(listings, args, estimator)

        st.success(f"Found {len(recommendations)} recommendations")
        st.caption("Cash-on-Cash (CoC) = Annual Pre-Tax Cash Flow ÷ Total Cash Invested. We use annual net cashflow / down payment.")
        if not recommendations:
            st.info("No positive-cashflow listings found. Try increasing down payment or reducing purchase price.")
        else:
            rows = []
            for rec in recommendations:
                search_address = f"{rec.listing.address}, {rec.listing.city}, {rec.listing.state} {rec.listing.zip_code}"
                rows.append(
                    {
                        "Address": search_address,
                        "Type": rec.listing.property_type,
                        "Price": rec.listing.price,
                        "Beds": rec.listing.bedrooms,
                        "Baths": rec.listing.bathrooms,
                        "Sqft": rec.listing.sqft,
                        "Est Rent/mo": rec.estimated_rent,
                        "Rent Method": rec.rent_estimation_method,
                        "P&I/mo": rec.monthly_mortgage_pi,
                        "Tax/mo": rec.monthly_taxes,
                        "Insurance/mo": rec.monthly_insurance,
                        "PMI/mo": rec.monthly_pmi,
                        "HOA/mo": rec.monthly_hoa,
                        "Mgmt/mo": rec.monthly_management,
                        "Maint/mo": rec.monthly_maintenance,
                        "Net Cashflow/mo": rec.monthly_net_cashflow,
                        "CoC Return %": rec.annual_cash_on_cash_return,
                        "Down %": rec.down_payment_pct,
                        "Listing": rec.listing.listing_url or f"https://www.zillow.com/homes/{quote_plus(search_address)}_rb/",
                        "Redfin": f"https://www.redfin.com/city/{quote_plus(rec.listing.city)}",
                    }
                )

            df = pd.DataFrame(rows).sort_values("Net Cashflow/mo", ascending=False)
            st.dataframe(
                df.style.format(
                    {
                        "Price": "${:,.0f}",
                        "Est Rent/mo": "${:,.0f}",
                        "P&I/mo": "${:,.0f}",
                        "Tax/mo": "${:,.0f}",
                        "Insurance/mo": "${:,.0f}",
                        "PMI/mo": "${:,.0f}",
                        "HOA/mo": "${:,.0f}",
                        "Mgmt/mo": "${:,.0f}",
                        "Maint/mo": "${:,.0f}",
                        "Net Cashflow/mo": "${:,.0f}",
                        "CoC Return %": "{:.2f}",
                        "Down %": "{:.1f}",
                    }
                ),
                use_container_width=True,
            )

            st.subheader("Monthly cost stack (top recommendation)")
            top = recommendations[0]
            breakdown = pd.DataFrame(
                {
                    "Category": ["P&I", "HOA", "Property Tax", "Management", "Maintenance", "Landlord Insurance", "PMI", "Net Cashflow"],
                    "Monthly $": [top.monthly_mortgage_pi, top.monthly_hoa, top.monthly_taxes, top.monthly_management, top.monthly_maintenance, top.monthly_insurance, top.monthly_pmi, top.monthly_net_cashflow],
                }
            )
            st.bar_chart(breakdown.set_index("Category"))

    except Exception as exc:
        st.error(f"Analysis failed: {exc}")

st.markdown("---")
st.caption("Tip: set RAPIDAPI_KEY in Streamlit secrets (.streamlit/secrets.toml locally or app secrets in deployment).")
