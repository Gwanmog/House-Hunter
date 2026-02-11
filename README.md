# House Hunter Investment Recommender

This app scans active homes for sale and recommends properties likely to generate **positive monthly cashflow** as long-term rentals.

## What it takes as input

- **Location**: state abbreviation (`TX`) or ZIP code (`75201`)
- **Budget constraints**:
  - max purchase price
  - max down payment
- **House preferences (weighted)**:
  - square footage
  - bedrooms
  - bathrooms
  - year built
  - lot size
- **Financing + operating assumptions**:
  - mortgage rate / term
  - insurance
  - maintenance reserve
  - property management fee
  - vacancy reserve

## What it computes

For each listing:

1. Estimated monthly rent (heuristic and/or local rental comps)
2. Mortgage principal + interest
3. Property tax
4. Insurance
5. Maintenance reserve
6. Management fee
7. Vacancy reserve
8. Net monthly cashflow

Output includes **only listings with net cashflow > 0**.

## Data sources for for-sale homes

### CSV mode (default)
Use a CSV with headers:

```csv
listing_id,address,city,state,zip_code,price,sqft,bedrooms,bathrooms,year_built,lot_size_sqft,hoa_monthly
```

Sample: `data/listings_sample.csv`

### RapidAPI mode
Use live listings from your subscribed host.

Relevant flags:

- `--rapidapi-key` or `RAPIDAPI_KEY`
- `--config-file` (default `.house_hunter.env`)
- `--rapidapi-host` (default `realtor-search.p.rapidapi.com`)
- `--rapidapi-endpoint` (default `/properties/v3/list`)
- `--rapidapi-limit`

Example:

```bash
python3 app.py \
  --source rapidapi-realtor \
  --location 75201 \
  --max-price 350000 \
  --max-down-payment 70000 \
  --rapidapi-host realty-in-us.p.rapidapi.com \
  --rapidapi-endpoint /properties/v3/list
```

If your subscribed API uses a different path or query format, set the endpoint accordingly.

### Secrets / key storage

You can store secrets locally in a config file so you don't paste keys every run.

Create `.house_hunter.env` in the repo root:

```bash
cat > .house_hunter.env <<'EOF'
RAPIDAPI_KEY=your_real_key_here
EOF
```

Then run normally (the app auto-loads this file), or pass a custom file path with `--config-file`.

## Rent estimation quality (local comps)

To improve rent quality, the app now supports **ZIP-level rental comparable analysis**.

### Rent sources

`--rent-source` options:

- `heuristic`: old model only
- `csv`: from your rental comp CSV only
- `rapidapi-realtor`: live rental comps from API only
- `hybrid` (default): CSV/API comps first, fallback to heuristic

Rental API flags:
- `--rapidapi-rent-endpoint`
- `--rapidapi-rent-method` (`GET` or `POST`)
- `--rapidapi-rent-location-param`
- `--rapidapi-rent-limit`

### Rental comp matching logic

The app compares properties in the **same ZIP** and weights each comp by similarity:

- bedrooms
- bathrooms
- square footage
- year built
- lot size

Then it calculates a weighted median rent from matching comps.

### Rental comps CSV format

Use a CSV with headers:

```csv
comp_id,address,city,state,zip_code,monthly_rent,sqft,bedrooms,bathrooms,year_built,lot_size_sqft
```

Sample: `data/rental_comps_sample.csv`

CSV comp run example:

```bash
python3 app.py \
  --source csv \
  --listings-csv data/listings_sample.csv \
  --rent-source csv \
  --rental-comps-csv data/rental_comps_sample.csv \
  --location TX \
  --max-price 350000 \
  --max-down-payment 70000
```

API comp run example (hybrid):

```bash
python3 app.py \
  --source rapidapi-realtor \
  --rent-source hybrid \
  --location 75201 \
  --max-price 350000 \
  --max-down-payment 70000 \
  --rapidapi-host realty-in-us.p.rapidapi.com \
  --rapidapi-endpoint /properties/v3/list \
  --rapidapi-rent-endpoint /properties/v3/list-for-rent \
  --rapidapi-method POST \
  --rapidapi-location-param postal_code \
  --rapidapi-rent-method POST \
  --rapidapi-rent-location-param postal_code
```

## If live API still doesn't work

Do this on RapidAPI website (API tester), then mirror values in CLI:

1. Open your subscribed API, copy the working request exactly (method, path, params/body).
2. Map to CLI:
   - host -> `--rapidapi-host`
   - path -> `--rapidapi-endpoint`
   - method -> `--rapidapi-method`
   - ZIP field name (`zip`/`postal_code`) -> `--rapidapi-location-param`
3. For rental comps endpoint, repeat mapping with `--rapidapi-rent-*` flags.
4. Ensure plan includes both for-sale and for-rent endpoints when using `--rent-source hybrid`.
5. Confirm quota and billing are active.

If you share one successful RapidAPI test request/response from the tester, we can tune the final field mapping in minutes.

## Notes

- This tool is an underwriting helper, not financial advice.
- Replace assumptions with local market data before investment decisions.
- If a key is exposed in chat/commits, rotate it immediately.
