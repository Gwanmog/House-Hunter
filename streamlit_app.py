#!/usr/bin/env python3
"""Streamlit UI for House Hunter investment analysis."""

from __future__ import annotations

from types import SimpleNamespace

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


def build_args(
    source,
    listings_csv,
    location,
    max_price,
    max_down_payment,
    interest_rate,
    loan_years,
    target_sqft,
    target_bedrooms,
    target_bathrooms,
    target_year_built,
    target_lot_size,
    weight_sqft,
    weight_bedrooms,
    weight_bathrooms,
    weight_year_built,
    weight_lot_size,
    insurance_rate,
    maintenance_rate,
    management_rate,
    vacancy_rate,
    results,
    rapidapi_host,
    rapidapi_endpoint,
    rapidapi_limit,
    rapidapi_method,
    rapidapi_location_param,
    rent_source,
    rental_comps_csv,
    rapidapi_rent_endpoint,
    rapidapi_rent_limit,
    rapidapi_rent_method,
    rapidapi_rent_location_param,
    min_rent_comps,
):
    return SimpleNamespace(
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
        maintenance_rate=float(maintenance_rate),
        management_rate=float(management_rate),
        vacancy_rate=float(vacancy_rate),
        results=int(results),
        rapidapi_key=secret_value("RAPIDAPI_KEY", None),
        config_file=".house_hunter.env",
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
    )


st.set_page_config(page_title="House Hunter", layout="wide")
st.title("🏠 House Hunter Investment Recommender")
st.caption("Find active listings with projected positive cashflow.")

# Core controls (center, most important)
col_a, col_b, col_c = st.columns(3)
with col_a:
    location = st.text_input("Location (ZIP or State)", value=str(secret_value("DEFAULT_LOCATION", "76131")))
    max_price = st.number_input("Max Purchase Price", min_value=50000, value=secret_int("DEFAULT_MAX_PRICE", 900000), step=10000)
    max_down_payment = st.number_input("Max Down Payment", min_value=1000, value=secret_int("DEFAULT_MAX_DOWN_PAYMENT", 300000), step=5000)

with col_b:
    interest_rate = st.number_input("Interest Rate (%)", min_value=0.0, value=secret_float("DEFAULT_INTEREST_RATE", 5.75), step=0.1)
    loan_years = st.number_input("Loan Term (years)", min_value=5, value=30, step=5)
    insurance_rate = st.number_input(
        "Insurance Rate (annual pct of price)",
        min_value=0.0,
        value=secret_float("DEFAULT_INSURANCE_RATE", 0.0035),
        step=0.0005,
        format="%.4f",
    )

with col_c:
    maintenance_rate = st.number_input("Maintenance Rate (pct of rent)", min_value=0.0, value=secret_float("DEFAULT_MAINTENANCE_RATE", 0.05), step=0.01)
    management_rate = st.number_input("Management Rate (pct of rent)", min_value=0.0, value=secret_float("DEFAULT_MANAGEMENT_RATE", 0.07), step=0.01)
    vacancy_rate = st.number_input("Vacancy Rate (pct of rent)", min_value=0.0, value=secret_float("DEFAULT_VACANCY_RATE", 0.03), step=0.01)

st.info("Default mode uses live API listings. Open **Advanced settings** if you need to switch source or endpoints.")

# Advanced panel (collapsed by default)
with st.expander("Advanced settings", expanded=False):
    st.subheader("Data Source")
    source_default = str(secret_value("DEFAULT_SOURCE", "rapidapi-realtor"))
    source = st.selectbox(
        "Listing Source",
        ["rapidapi-realtor", "csv"],
        index=0 if source_default == "rapidapi-realtor" else 1,
        help="rapidapi-realtor = live market feed, csv = local/offline file",
    )
    listings_csv = st.text_input("Listings CSV", value="data/listings_sample.csv")
    rental_comps_csv = st.text_input("Rental comps CSV (optional)", value="data/rental_comps_sample.csv")

    st.subheader("Rent Source")
    st.caption(
        "hybrid = try rental comps (API/CSV) first, fallback to heuristic (recommended). "
        "rapidapi-realtor = API comps only. csv = CSV comps only. heuristic = formula only."
    )
    rent_source_default = str(secret_value("DEFAULT_RENT_SOURCE", "hybrid"))
    rent_options = ["hybrid", "rapidapi-realtor", "csv", "heuristic"]
    default_index = rent_options.index(rent_source_default) if rent_source_default in rent_options else 0
    rent_source = st.selectbox("Rent Source", rent_options, index=default_index)

    results = st.slider("Max recommendations", 1, 25, secret_int("DEFAULT_RESULTS", 5), step=1)
    min_rent_comps = st.slider("Minimum rent comps", 1, 20, secret_int("DEFAULT_MIN_RENT_COMPS", 2))

    st.subheader("API Config")
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

# Safe defaults when expander stays closed
if "source" not in locals():
    source = str(secret_value("DEFAULT_SOURCE", "rapidapi-realtor"))
if "listings_csv" not in locals():
    listings_csv = "data/listings_sample.csv"
if "rental_comps_csv" not in locals():
    rental_comps_csv = "data/rental_comps_sample.csv"
if "rent_source" not in locals():
    rent_source = str(secret_value("DEFAULT_RENT_SOURCE", "hybrid"))
if "results" not in locals():
    results = secret_int("DEFAULT_RESULTS", 5)
if "min_rent_comps" not in locals():
    min_rent_comps = secret_int("DEFAULT_MIN_RENT_COMPS", 2)
if "rapidapi_host" not in locals():
    rapidapi_host = secret_value("RAPIDAPI_HOST", "realty-in-us.p.rapidapi.com")
if "rapidapi_endpoint" not in locals():
    rapidapi_endpoint = secret_value("RAPIDAPI_SALE_ENDPOINT", "/properties/v3/list")
if "rapidapi_method" not in locals():
    rapidapi_method = str(secret_value("RAPIDAPI_SALE_METHOD", "POST")).upper()
if "rapidapi_location_param" not in locals():
    rapidapi_location_param = secret_value("RAPIDAPI_SALE_LOCATION_PARAM", "postal_code")
if "rapidapi_rent_endpoint" not in locals():
    rapidapi_rent_endpoint = secret_value("RAPIDAPI_RENT_ENDPOINT", "/properties/v3/list")
if "rapidapi_rent_method" not in locals():
    rapidapi_rent_method = str(secret_value("RAPIDAPI_RENT_METHOD", "POST")).upper()
if "rapidapi_rent_location_param" not in locals():
    rapidapi_rent_location_param = secret_value("RAPIDAPI_RENT_LOCATION_PARAM", "postal_code")
if "rapidapi_limit" not in locals():
    rapidapi_limit = 100
if "rapidapi_rent_limit" not in locals():
    rapidapi_rent_limit = 120
if "target_sqft" not in locals():
    target_sqft = 1800
if "target_bedrooms" not in locals():
    target_bedrooms = 3.0
if "target_bathrooms" not in locals():
    target_bathrooms = 2.0
if "target_year_built" not in locals():
    target_year_built = 1995
if "target_lot_size" not in locals():
    target_lot_size = 7000
if "weight_sqft" not in locals():
    weight_sqft = 3.0
if "weight_bedrooms" not in locals():
    weight_bedrooms = 2.0
if "weight_bathrooms" not in locals():
    weight_bathrooms = 2.0
if "weight_year_built" not in locals():
    weight_year_built = 1.5
if "weight_lot_size" not in locals():
    weight_lot_size = 1.0

st.subheader("API connectivity check")
if st.button("Test RapidAPI listing fetch"):
    test_args = build_args(
        "rapidapi-realtor",
        listings_csv,
        location,
        max_price,
        max_down_payment,
        interest_rate,
        loan_years,
        target_sqft,
        target_bedrooms,
        target_bathrooms,
        target_year_built,
        target_lot_size,
        weight_sqft,
        weight_bedrooms,
        weight_bathrooms,
        weight_year_built,
        weight_lot_size,
        insurance_rate,
        maintenance_rate,
        management_rate,
        vacancy_rate,
        5,
        rapidapi_host,
        rapidapi_endpoint,
        5,
        rapidapi_method,
        rapidapi_location_param,
        "heuristic",
        rental_comps_csv,
        rapidapi_rent_endpoint,
        5,
        rapidapi_rent_method,
        rapidapi_rent_location_param,
        1,
    )
    try:
        fetched = load_listings(test_args)
        st.success(f"API fetch successful. Retrieved {len(fetched)} listing(s).")
        if fetched:
            sample = fetched[0]
            st.caption(f"Sample: {sample.address}, {sample.city}, {sample.state} {sample.zip_code} | ${sample.price:,.0f}")
    except Exception as exc:
        st.error(f"API fetch failed: {exc}")

if st.button("Run analysis", type="primary"):
    args = build_args(
        source,
        listings_csv,
        location,
        max_price,
        max_down_payment,
        interest_rate,
        loan_years,
        target_sqft,
        target_bedrooms,
        target_bathrooms,
        target_year_built,
        target_lot_size,
        weight_sqft,
        weight_bedrooms,
        weight_bathrooms,
        weight_year_built,
        weight_lot_size,
        insurance_rate,
        maintenance_rate,
        management_rate,
        vacancy_rate,
        results,
        rapidapi_host,
        rapidapi_endpoint,
        rapidapi_limit,
        rapidapi_method,
        rapidapi_location_param,
        rent_source,
        rental_comps_csv,
        rapidapi_rent_endpoint,
        rapidapi_rent_limit,
        rapidapi_rent_method,
        rapidapi_rent_location_param,
        min_rent_comps,
    )

    try:
        listings = load_listings(args)
        estimator = RentEstimator(args)
        recommendations = recommend(listings, args, estimator)

        st.success(f"Found {len(recommendations)} recommendations")
        if not recommendations:
            st.info("No positive-cashflow listings found. Try increasing down payment or reducing purchase price.")
        else:
            rows = []
            for rec in recommendations:
                rows.append(
                    {
                        "Address": f"{rec.listing.address}, {rec.listing.city}, {rec.listing.state} {rec.listing.zip_code}",
                        "Price": rec.listing.price,
                        "Beds": rec.listing.bedrooms,
                        "Baths": rec.listing.bathrooms,
                        "Sqft": rec.listing.sqft,
                        "Est Rent/mo": rec.estimated_rent,
                        "Rent Method": rec.rent_estimation_method,
                        "HOA/mo": rec.monthly_hoa,
                        "Net Cashflow/mo": rec.monthly_net_cashflow,
                        "CoC Return %": rec.annual_cash_on_cash_return,
                        "Score": rec.score,
                    }
                )

            df = pd.DataFrame(rows).sort_values("Net Cashflow/mo", ascending=False)
            st.dataframe(
                df.style.format(
                    {
                        "Price": "${:,.0f}",
                        "Est Rent/mo": "${:,.0f}",
                        "HOA/mo": "${:,.0f}",
                        "Net Cashflow/mo": "${:,.0f}",
                        "CoC Return %": "{:.2f}",
                        "Score": "{:.1f}",
                    }
                ),
                use_container_width=True,
            )

    except Exception as exc:
        st.error(f"Analysis failed: {exc}")

st.markdown("---")
st.caption("Tip: set RAPIDAPI_KEY in Streamlit secrets (.streamlit/secrets.toml locally or app secrets in deployment).")
