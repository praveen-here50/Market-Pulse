"""MarketPulse public demo: the real dashboard running on made-up prices.

Run with:  python -m streamlit run demo_app.py

Everything shown is sample data. See demo.py for what keeps it separate from real data.
"""

import demo

demo.activate()

import dashboard  # noqa: E402

dashboard.main()
