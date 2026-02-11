#!/usr/bin/env python3
"""Streamlit UI for House Hunter investment analysis."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import streamlit as st

from app import load_listings, recommend, RentEstimator


st.set_page_config(page_title="House Hunter", layout="wide")
st.title("🏠 House Hunter Investment Recommender")
st.caption("Find active listings with projected positive cashflow.")


with st.sidebar:
    st.header("Data Source")
    source = st.selectbox("Listing Source", ["csv", "rapidapi-realtor"], index=0)

    listings_csv = st.text_input("Listings CSV", value="data/listings_sample.csv")
    rental_comps_csv = st.text_input("Rental comps CSV (optional)", value="data/rental_comps_sample.csv")

    rapidapi_host = st.text_input("RapidAPI Host", value="realty-in-us.p.rapidapi.com")
    rapidapi_endpoint = st.text_input("RapidAPI Sale Endpoint", value="/properties/v3/list")
    rapidapi_method = st.selectbox("RapidAPI Sale Method", ["POST", "GET"], index=0)
    rapidapi_location_param = st.text_input("RapidAPI Sale Location Param", value="postal_code")

    rapidapi_rent_endpoint = st.text_input("RapidAPI Rent Endpoint", value="/properties/v3/list")
    rapidapi_rent_method = st.selectbox("RapidAPI Rent Method", ["POST", "GET"], index=0)
    rapidapi_rent_location_param = st.text_input("RapidAPI Rent Location Param", value="postal_code")

    rapidapi_limit = st.slider("Sale API Limit", 20, 200, 100, step=20)
    rapidapi_rent_limit = st.slider("Rent API Limit", 20, 200, 120, step=20)


col_a, col_b, col_c = st.columns(3)
with col_a:
    location = st.text_input("Location (ZIP or State)", value="76131")
    max_price = st.number_input("Max Purchase Price", min_value=50000, value=900000, step=10000)
    max_down_payment = st.number_input("Max Down Payment", min_value=1000, value=300000, step=5000)

with col_b:
    interest_rate = st.number_input("Interest Rate (%)", min_value=0.0, value=5.75, step=0.1)
    loan_years = st.number_input("Loan Term (years)", min_value=5, value=30, step=5)
    insurance_rate = st.number_input("Insurance Rate (annual pct of price)", min_value=0.0, value=0.0035, step=0.0005, format="%.4f")

with col_c:
    maintenance_rate = st.number_input("Maintenance Rate (pct of rent)", min_value=0.0, value=0.05, step=0.01)
    management_rate = st.number_input("Management Rate (pct of rent)", min_value=0.0, value=0.07, step=0.01)
    vacancy_rate = st.number_input("Vacancy Rate (pct of rent)", min_value=0.0, value=0.03, step=0.01)

with st.expander("Advanced preferences / scoring"):
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


rent_source = st.selectbox("Rent Source", ["hybrid", "rapidapi-realtor", "csv", "heuristic"], index=0)
results = st.slider("Max recommendations", 5, 50, 25, step=5)
min_rent_comps = st.slider("Minimum rent comps", 1, 20, 2)

if st.button("Run analysis", type="primary"):
    args = SimpleNamespace(
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
        rapidapi_key=None,
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
            st.dataframe(df.style.format({
                "Price": "${:,.0f}",
                "Est Rent/mo": "${:,.0f}",
                "HOA/mo": "${:,.0f}",
                "Net Cashflow/mo": "${:,.0f}",
                "CoC Return %": "{:.2f}",
                "Score": "{:.1f}",
            }), use_container_width=True)

    except Exception as exc:
        st.error(f"Analysis failed: {exc}")

st.markdown("---")
st.caption("Tip: put RAPIDAPI_KEY in .house_hunter.env for API usage.")
