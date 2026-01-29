#!/usr/bin/env python3
"""
Test script for return data loading

Updated to use dashboard.py (the consolidated version)
"""
import pandas as pd
import pickle
from datetime import datetime, date

# Import functions from dashboard
import sys
sys.path.insert(0, '/home/user/DB_OCIO')

from dashboard import (
    load_master_mapping,
    fetch_factset_returns_with_dates,
    calculate_return_periods_v2,
    should_exclude_for_scip_return,
    create_engine,
    CONN_STR_SCIP
)

print("="*80)
print("Testing Return Data Loading")
print("="*80)

# Load master
print("\n1. Loading master mapping...")
master = load_master_mapping()
print(f"   Loaded {len(master)} items")

# Check exclusions
print("\n2. Checking exclusions...")
master['exclude'] = master.apply(
    lambda row: should_exclude_for_scip_return(row['ITEM_NM'], row.get('대분류', '')), axis=1
)
excluded = master[master['exclude']]
included = master[~master['exclude']]
print(f"   Excluded: {len(excluded)} items")
print(f"   Included: {len(included)} items")

if len(excluded) > 0:
    print("\n   Excluded items sample:")
    for _, row in excluded.head(10).iterrows():
        print(f"     - {row['ITEM_NM']}")

# Test with SCIP DB
print(f"\n3. Fetching FactSet returns from SCIP...")

try:
    engine_scip = create_engine(CONN_STR_SCIP)
    factset_returns, available_dates, latest_date, base_dates = fetch_factset_returns_with_dates(master, engine_scip)
    print(f"   Retrieved {len(factset_returns)} datapoints")
    print(f"   Latest date: {latest_date}")
    print(f"   Base dates: {base_dates}")

    if len(factset_returns) > 0:
        print(f"   Date range: {factset_returns['date'].min()} to {factset_returns['date'].max()}")
        print(f"   Unique items: {factset_returns['ITEM_CD'].nunique()}")

        print("\n   Sample data:")
        sample = factset_returns.groupby('ITEM_CD').tail(1).head(5)
        print(sample[['ITEM_CD', 'date', 'return_index']].to_string(index=False))

    # Calculate returns
    print(f"\n4. Calculating return periods...")
    return_periods = calculate_return_periods_v2(factset_returns, latest_date, base_dates)
    print(f"   Calculated returns for {len(return_periods)} items")

    if len(return_periods) > 0:
        print("\n   Sample returns:")
        print(return_periods.head(10).to_string(index=False))

        # Check for items with data
        items_with_data = return_periods[return_periods['1M'].notna()]
        print(f"\n   Items with 1M return data: {len(items_with_data)}")

except Exception as e:
    print(f"   ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*80)
print("Test Complete")
print("="*80)
