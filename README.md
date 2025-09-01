# CrowdWisdomTrading — SEC Insider Activity Agents

End‑to‑end, **fully functional** Python project that:
1) Downloads **live SEC EDGAR filings** for **Form 4 / 4/A** in the **last 24 hours**.
2) Parses insider transactions from each filing’s `form4.xml`.
3) Aggregates activity by **issuer (ticker)** and **transaction code** (P, S, etc.).
4) Compares last 24h vs. prior **7 days** (daily average).
5) Generates a **report JSON** and **chart PNG**, and optionally runs the same pipeline through **CrewAI agents** (flow + tools).

> You can run the **plain Python pipeline** without any LLM/API keys.  
> The **CrewAI flow** is optional and needs an LLM provider via LiteLLM (OpenAI/other).

---

## Quick Start (no LLM required)

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run the pipeline (fetches live SEC data)
python run.py
```

Outputs are saved to `data/` and `charts/`:
- `data/last24h_insider_summary.json`
- `data/weekly_baseline.json`
- `data/final_report.json`
- `charts/insider_activity_last24h.png`

A single plain‑text **report** is also printed to the console.

---

## Optional: Run with CrewAI (Flow + Agents)

Set an environment variable for LiteLLM, e.g. with OpenAI:
```bash
export OPENAI_API_KEY=sk-...        # Windows: set OPENAI_API_KEY=...
python crewai_flow/crew_flow.py
```

This will orchestrate the same tools via CrewAI Agents (Data → Insider → Compare → Report)
and will save the same artifacts in `data/` and `charts/`.

---

## Notes
- We respect SEC’s fair‑use policy using a descriptive `User-Agent` and modest rate limiting.
- We use the **EDGAR Daily Index** (`master.YYYYMMDD.idx`) to list all Form 4 filings
  and then fetch the filing directory’s `index.json` to locate the **`form4.xml`** for parsing.
- If a filing is missing XML (rare), it’s skipped safely.

## Files
- `run.py` — plain Python pipeline (no LLM needed).
- `sec_tools.py` — reusable functions for downloading and parsing EDGAR data.
- `crewai_flow/crew_flow.py` — CrewAI version that calls the same tools as agent functions.
- `requirements.txt` — dependencies.
- `README.md` — this file.

Good luck!
