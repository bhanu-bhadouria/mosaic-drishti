# Nifty 50 stocks in yfinance format (NSE suffix)
# This is our research universe — the stocks Mosaic Drishti will track
# Add or remove symbols here to expand/shrink the universe

NIFTY_50 = {
    "RELIANCE.NS": "Reliance Industries",
    "TCS.NS": "Tata Consultancy Services",
    "HDFCBANK.NS": "HDFC Bank",
    "INFY.NS": "Infosys",
    "ICICIBANK.NS": "ICICI Bank",
    "HINDUNILVR.NS": "Hindustan Unilever",
    "SBIN.NS": "State Bank of India",
    "BHARTIARTL.NS": "Bharti Airtel",
    "KOTAKBANK.NS": "Kotak Mahindra Bank",
    "ITC.NS": "ITC Limited",
    "LT.NS": "Larsen & Toubro",
    "AXISBANK.NS": "Axis Bank",
    "ASIANPAINT.NS": "Asian Paints",
    "MARUTI.NS": "Maruti Suzuki",
    "SUNPHARMA.NS": "Sun Pharmaceutical",
    "TITAN.NS": "Titan Company",
    "ULTRACEMCO.NS": "UltraTech Cement",
    "BAJFINANCE.NS": "Bajaj Finance",
    "NESTLEIND.NS": "Nestle India",
    "WIPRO.NS": "Wipro",
}

# Start with 20 stocks — enough to build and test the pipeline
# Full Nifty 50 can be added once ingestion is stable

def get_all_tickers() -> list[str]:
    """Return list of all ticker symbols in the universe."""
    return list(NIFTY_50.keys())


def get_company_name(ticker: str) -> str:
    """Return company name for a given ticker symbol."""
    return NIFTY_50.get(ticker, "Unknown")