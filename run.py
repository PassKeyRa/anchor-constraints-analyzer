#!/usr/bin/env python3

import sys
import argparse
import json
from pathlib import Path

from constraint_extractor import extract_constraints_from_file
from definition_analyzer import (
    DefinitionAnalyzer,
    save_definition_graph,
    print_analysis_summary
)


def find_rust_files(path):
    rust_files = []
    path_obj = Path(path)

    if path_obj.is_file():
        if path_obj.suffix == '.rs':
            rust_files.append(path_obj)
    elif path_obj.is_dir():
        rust_files = list(path_obj.rglob('*.rs'))

    return sorted(rust_files)


def analyze_single_file(filepath, output_path=None, quiet=False):
    if not quiet:
        print(f"Analyzing {filepath}...\n")

    constraints_list = extract_constraints_from_file(str(filepath))

    if not constraints_list:
        if not quiet:
            print(f"No constraint structs found in {filepath}\n")
        return []

    results = []
    for constraints in constraints_list:
        analyzer = DefinitionAnalyzer(constraints)
        graph = analyzer.analyze()

        if not quiet:
            print_analysis_summary(graph)

        results.append({
            'file': str(filepath),
            'struct': constraints.name,
            'graph': graph.to_dict()
        })

    if output_path and len(constraints_list) == 1:
        save_definition_graph(graph, output_path)

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Anchor constraint structs and generate definition graphs"
    )
    parser.add_argument(
        "input_path",
        help="Path to Rust source file or directory to analyze"
    )
    parser.add_argument(
        "output_path",
        nargs="?",
        help="Output path for definition graph (JSON). For directories, aggregates all results."
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress console output, only save to file"
    )

    args = parser.parse_args()

    input_path = Path(args.input_path)
    if not input_path.exists():
        print(f"Error: Path '{args.input_path}' not found", file=sys.stderr)
        sys.exit(1)

    rust_files = find_rust_files(input_path)

    if not rust_files:
        print(f"No Rust files found in '{args.input_path}'", file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f"Found {len(rust_files)} Rust file(s)\n")
        print("=" * 80 + "\n")

    all_results = []
    for rust_file in rust_files:
        results = analyze_single_file(rust_file, None, args.quiet)
        all_results.extend(results)

        if not args.quiet and len(rust_files) > 1:
            print("\n" + "=" * 80 + "\n")

    if args.output_path:
        output_path = Path(args.output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if len(all_results) == 1:
            with open(output_path, 'w') as f:
                f.write(json.dumps(all_results[0]['graph'], indent=2))
        else:
            with open(output_path, 'w') as f:
                f.write(json.dumps({
                    'total_files': len(rust_files),
                    'total_structs': len(all_results),
                    'results': all_results
                }, indent=2))

        print(f"Results saved to {output_path}")


if __name__ == "__main__":
    main()
