#!/usr/bin/env python3
"""
Rust file parser using tree-sitter.
Parses .rs files and provides AST traversal capabilities.
"""

import sys
from pathlib import Path
from tree_sitter import Language, Parser
import tree_sitter_rust


def setup_parser():
    """Initialize tree-sitter parser for Rust."""
    RUST_LANGUAGE = Language(tree_sitter_rust.language())
    parser = Parser(RUST_LANGUAGE)
    return parser


def parse_file(filepath):
    """Parse a Rust file and return the syntax tree."""
    parser = setup_parser()

    # Read the file
    with open(filepath, 'rb') as f:
        source_code = f.read()

    # Parse the code
    tree = parser.parse(source_code)
    return tree, source_code


def print_tree(node, source_code, indent=0):
    """Recursively print the syntax tree."""
    # Get the actual text for this node
    node_text = source_code[node.start_byte:node.end_byte].decode('utf-8')

    # Limit text display to first 50 characters
    if len(node_text) > 50:
        node_text = node_text[:50] + "..."
    node_text = node_text.replace('\n', '\\n')

    # Print node information
    print("  " * indent + f"{node.type} [{node.start_point[0]}:{node.start_point[1]} - {node.end_point[0]}:{node.end_point[1]}]", end="")
    if node.child_count == 0:
        print(f" → '{node_text}'")
    else:
        print()

    # Recursively print children
    for child in node.children:
        print_tree(child, source_code, indent + 1)


def find_nodes_by_type(node, node_type):
    """Find all nodes of a specific type in the tree."""
    results = []

    if node.type == node_type:
        results.append(node)

    for child in node.children:
        results.extend(find_nodes_by_type(child, node_type))

    return results


def main():
    if len(sys.argv) < 2:
        print("Usage: python parse_rust.py <rust_file.rs>")
        sys.exit(1)

    filepath = sys.argv[1]

    if not Path(filepath).exists():
        print(f"Error: File '{filepath}' not found")
        sys.exit(1)

    print(f"Parsing {filepath}...\n")

    tree, source_code = parse_file(filepath)
    root_node = tree.root_node

    print("=" * 80)
    print("SYNTAX TREE")
    print("=" * 80)
    print_tree(root_node, source_code)

    # Example: Find all function items
    print("\n" + "=" * 80)
    print("FUNCTIONS")
    print("=" * 80)
    functions = find_nodes_by_type(root_node, "function_item")
    print(f"Found {len(functions)} function(s)")

    for func in functions:
        func_text = source_code[func.start_byte:func.end_byte].decode('utf-8')
        first_line = func_text.split('\n')[0]
        print(f"  - {first_line}...")


if __name__ == "__main__":
    main()
