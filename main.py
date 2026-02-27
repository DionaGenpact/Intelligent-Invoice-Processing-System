import argparse
from agents.orchestrator import run_pipeline

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    args = parser.parse_args()

    run_pipeline(args.bundle)

if __name__ == "__main__":
    main()