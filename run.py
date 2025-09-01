from sec_tools import run_pipeline

if __name__ == "__main__":
    report = run_pipeline(output_dir="data", charts_dir="charts", max_filings=250)
    print("=== Final Report Summary ===")
    print(report)
    print("\nArtifacts saved under ./data and ./charts")
