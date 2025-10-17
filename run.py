#!/usr/bin/env python3

import sys
import argparse
from pathlib import Path

from constraint_extractor import extract_constraints_from_file
from definition_analyzer import (
    DefinitionAnalyzer,
    save_definition_graph,
    print_analysis_summary
)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Anchor constraint structs and generate definition graphs"
    )
    parser.add_argument(
        "input_file",
        help="Path to the Rust source file to analyze"
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        help="Optional output path for the definition graph (JSON format)"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output, only save to file"
    )

    args = parser.parse_args()

    if not Path(args.input_file).exists():
        print(f"Error: File '{args.input_file}' not found", file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f"Analyzing {args.input_file}...\n")

    constraints_list = extract_constraints_from_file(args.input_file)

    if not constraints_list:
        print("No constraint structs found", file=sys.stderr)
        sys.exit(1)

    for constraints in constraints_list:
        analyzer = DefinitionAnalyzer(constraints)
        graph = analyzer.analyze()

        if not args.quiet:
            print_analysis_summary(graph)

        if args.output_path:
            save_definition_graph(graph, args.output_path)


if __name__ == "__main__":
    main()
