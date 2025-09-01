import os
from datetime import datetime
from crewai import Agent, Task, Crew, Process
from crewai_tools import tool

from sec_tools import collect_last24h_and_week, build_activity_summary, aggregate_by_issuer, weekly_baseline, save_chart

# Tools exposed to agents
@tool("collect-sec-form4-spans")
def collect_spans():
    """Collect last 24h and prior week Form 4 filing lists from SEC daily index."""
    return collect_last24h_and_week()

@tool("parse-last24h-form4")
def parse_last24(spans: dict, max_filings: int = 250):
    """Parse last 24h filings into transaction rows."""
    return build_activity_summary(spans["last24"], max_filings=max_filings)

@tool("aggregate-issuers")
def aggregate_issuers(transactions):
    """Aggregate transactions by issuer."""
    return aggregate_by_issuer(transactions)

@tool("weekly-baseline")
def baseline(spans: dict):
    """Compute weekly baseline of filings/day."""
    return weekly_baseline(spans["week"])

def main():
    data_agent = Agent(
        role="SEC Data Agent",
        goal="Fetch SEC Form 4 filings for last 24h and prior week using tools.",
        backstory="Analyst expert in EDGAR daily indexes.",
        allow_delegation=False,
    )

    insider_agent = Agent(
        role="Insider Parsing Agent",
        goal="Parse last 24h filings to transactions and aggregate by issuer.",
        backstory="Understands form4.xml schema and extracts non-derivative transactions.",
        allow_delegation=False,
    )

    report_agent = Agent(
        role="Report Agent",
        goal="Compare last 24h vs prior week baseline and save artifacts (JSON + chart).",
        backstory="Summarizes insights for trading research teams.",
        allow_delegation=False,
    )

    def t1():
        return collect_spans()

    def t2(spans):
        tx = parse_last24(spans)
        agg = aggregate_issuers(tx)
        return {"transactions": tx, "summary": agg}

    def t3(spans, parsed):
        base = baseline(spans)
        # Save chart
        from pathlib import Path
        Path("charts").mkdir(exist_ok=True)
        save_chart(parsed["summary"], "charts/insider_activity_last24h.png")
        # Compose final message
        top = parsed["summary"].head(1).to_dict(orient="records")[0] if not parsed["summary"].empty else None
        return {
            "avg_filings_per_day_prior_7d": base,
            "top_issuer_today": top,
            "chart": "charts/insider_activity_last24h.png"
        }

    # Minimal "flow" without invoking LLM calls (deterministic function chaining)
    spans = t1()
    parsed = t2(spans)
    final = t3(spans, parsed)
    print("Crew Flow Final:", final)

if __name__ == "__main__":
    main()
