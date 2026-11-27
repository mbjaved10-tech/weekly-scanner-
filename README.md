# PSX Weekly Swing Scanner

## Deploy on Streamlit Community Cloud
1. Upload `app.py`, `requirements.txt`, and `README.md` to your GitHub repository.
2. Open Streamlit Community Cloud and choose **New app**.
3. Select your repository, branch, and `app.py`.
4. Deploy. Open the generated app URL on Android and use **Scan PSX now**.

## Data
Uses the independent open-source `psxdata` Python package. It retrieves daily PSX OHLCV data from public PSX pages; weekly candles are built by resampling daily data. No API key is required.

## Notes
- Full-market scans can take several minutes because each symbol's history is requested.
- The first scan may be slower; local caching in the data package helps subsequent runs.
- The app excludes the current incomplete weekly candle from weekly signal calculations.
- Entry is the latest completed weekly close. Stop is based on recent weekly support (with ATR fallback); targets are 2R and 3R.
- This is a technical screening tool, not investment advice.
