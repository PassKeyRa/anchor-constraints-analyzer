#!/usr/bin/env python3
"""
Extract and parse Anchor constraint structs from Rust source files.
"""

from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path
import re

from parser import setup_parser, parse_file, find_nodes_by_type
from constraint_types import (
    Constraints, AccountField, InstructionArgument, ConstraintAttribute,
    SeedsConstraint, AssociatedTokenConstraint, CustomConstraint, AccountType
)


class ConstraintExtractor:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.tree, self.source_code = parse_file(filepath)
        self.source_lines = self.source_code.decode('utf-8').split('\n')

    def extract_all_constraints(self) -> List[Constraints]:
        """Extract all constraint structs from the file."""
        constraints_list = []

        # Find all struct items
        structs = find_nodes_by_type(self.tree.root_node, "struct_item")

        for struct_node in structs:
            # Check if this struct has #[derive(Accounts)]
            if self._has_derive_accounts(struct_node):
                constraint = self._parse_constraint_struct(struct_node)
                if constraint:
                    constraints_list.append(constraint)

        return constraints_list

    def _has_derive_accounts(self, struct_node) -> bool:
        """Check if struct has #[derive(Accounts)] attribute."""
        # Look at previous siblings for attribute_item nodes
        parent = struct_node.parent
        if not parent:
            return False

        # Get all children of the parent up to this struct
        for i, child in enumerate(parent.children):
            if child == struct_node:
                # Look backwards for attribute_item
                for j in range(i - 1, -1, -1):
                    prev_child = parent.children[j]
                    if prev_child.type == "attribute_item":
                        attr_text = self._get_node_text(prev_child)
                        if "derive" in attr_text and "Accounts" in attr_text:
                            return True
                    elif prev_child.type not in ["line_comment", "block_comment"]:
                        # Stop if we hit a non-attribute, non-comment node
                        break
                break

        return False

    def _parse_constraint_struct(self, struct_node) -> Optional[Constraints]:
        """Parse a constraint struct into a Constraints object."""
        # Get struct name
        name_node = self._find_child_by_type(struct_node, "type_identifier")
        if not name_node:
            return None

        struct_name = self._get_node_text(name_node)

        # Get line numbers
        line_start = struct_node.start_point[0] + 1
        line_end = struct_node.end_point[0] + 1

        # Parse instruction arguments
        instruction_args = self._parse_instruction_args(struct_node)

        # Parse account fields
        accounts = self._parse_account_fields(struct_node)

        return Constraints(
            name=struct_name,
            instruction_args=instruction_args,
            accounts=accounts,
            source_file=self.filepath,
            line_start=line_start,
            line_end=line_end
        )

    def _parse_instruction_args(self, struct_node) -> List[InstructionArgument]:
        """Parse #[instruction(...)] macro arguments."""
        args = []

        # Look for attribute_item nodes before the struct
        parent = struct_node.parent
        if not parent:
            return args

        for i, child in enumerate(parent.children):
            if child == struct_node:
                # Look backwards for #[instruction(...)]
                for j in range(i - 1, -1, -1):
                    prev_child = parent.children[j]
                    if prev_child.type == "attribute_item":
                        attr_text = self._get_node_text(prev_child)
                        if "instruction" in attr_text:
                            args = self._extract_instruction_args(attr_text)
                            break
                break

        return args

    def _extract_instruction_args(self, attr_text: str) -> List[InstructionArgument]:
        """Extract instruction arguments from #[instruction(...)] text."""
        args = []

        # Match pattern: #[instruction(arg1: Type1, arg2: Type2, ...)]
        match = re.search(r'#\[instruction\((.*?)\)\]', attr_text, re.DOTALL)
        if not match:
            return args

        args_text = match.group(1)

        # Split by comma, but be careful with nested generics
        arg_parts = self._smart_split(args_text, ',')

        for part in arg_parts:
            part = part.strip()
            if ':' in part:
                name, type_name = part.split(':', 1)
                args.append(InstructionArgument(
                    name=name.strip(),
                    type_name=type_name.strip()
                ))

        return args

    def _parse_account_fields(self, struct_node) -> List[AccountField]:
        """Parse all account fields from the struct."""
        accounts = []

        # Find the field_declaration_list (struct body)
        field_list = self._find_child_by_type(struct_node, "field_declaration_list")
        if not field_list:
            return accounts

        # Process each field
        for child in field_list.children:
            if child.type == "field_declaration":
                account = self._parse_account_field(child)
                if account:
                    accounts.append(account)

        return accounts

    def _parse_account_field(self, field_node) -> Optional[AccountField]:
        """Parse a single account field."""
        # Get field name
        name_node = self._find_child_by_type(field_node, "field_identifier")
        if not name_node:
            return None

        field_name = self._get_node_text(name_node)

        # Get field type
        type_node = self._find_child_by_field(field_node, "type")
        if not type_node:
            return None

        type_name = self._get_node_text(type_node)

        # Get line number
        line_number = field_node.start_point[0] + 1

        # Extract inline comment if any
        comment = self._extract_inline_comment(field_node)

        # Parse attributes (constraints)
        attributes = self._parse_field_attributes(field_node)

        # Analyze and categorize the account
        account = self._create_account_field(
            field_name, type_name, attributes, line_number, comment
        )

        return account

    def _parse_field_attributes(self, field_node) -> List[ConstraintAttribute]:
        """Parse all #[account(...)] attributes for a field."""
        attributes = []

        # Look backwards for attribute_item nodes
        parent = field_node.parent
        if not parent:
            return attributes

        for i, child in enumerate(parent.children):
            if child == field_node:
                # Look backwards for attributes
                for j in range(i - 1, -1, -1):
                    prev_child = parent.children[j]
                    if prev_child.type == "attribute_item":
                        attr_text = self._get_node_text(prev_child)
                        # Check if it's an #[account(...)] attribute
                        if attr_text.startswith("#[account"):
                            attrs = self._parse_account_attribute(attr_text)
                            attributes.extend(attrs)
                    elif prev_child.type not in ["line_comment", "block_comment"]:
                        # Stop at non-attribute, non-comment
                        break
                break

        return attributes

    def _parse_account_attribute(self, attr_text: str) -> List[ConstraintAttribute]:
        """Parse individual constraints from #[account(...)] text."""
        attributes = []

        # Extract content inside #[account(...)]
        # Need to handle nested parentheses properly
        content = self._extract_attribute_content(attr_text)
        if not content:
            return attributes

        # Remove comments from content before parsing
        content = self._remove_comments(content)

        # Parse constraints - this is complex due to nested structures
        # We'll use a simple approach: split by commas not inside brackets/parens
        constraints = self._smart_split(content, ',')

        for constraint in constraints:
            constraint = constraint.strip()
            if not constraint:
                continue

            # Check if it has '=' (key = value)
            if '=' in constraint:
                parts = constraint.split('=', 1)
                key = parts[0].strip()
                value = parts[1].strip() if len(parts) > 1 else None
                attributes.append(ConstraintAttribute(name=key, value=value))
            else:
                # Simple flag (e.g., 'mut', 'bump')
                attributes.append(ConstraintAttribute(name=constraint))

        return attributes

    def _remove_comments(self, text: str) -> str:
        """Remove // comments from text."""
        lines = text.split('\n')
        cleaned_lines = []
        for line in lines:
            # Remove // comments but preserve the rest
            if '//' in line:
                line = line[:line.index('//')]
            cleaned_lines.append(line)
        return '\n'.join(cleaned_lines)

    def _create_account_field(
        self,
        name: str,
        type_name: str,
        attributes: List[ConstraintAttribute],
        line_number: int,
        comment: Optional[str]
    ) -> AccountField:
        """Create an AccountField with parsed constraint data."""

        # Determine account type
        account_type = self._determine_account_type(type_name, attributes)

        # Initialize account field
        account = AccountField(
            name=name,
            type_name=type_name,
            account_type=account_type,
            line_number=line_number,
            comment=comment,
            raw_attributes=attributes
        )

        # Parse constraint flags
        account.is_mut = any(attr.name == "mut" for attr in attributes)
        account.is_init = any(attr.name == "init" for attr in attributes)
        account.is_init_if_needed = any(attr.name == "init_if_needed" for attr in attributes)

        # Parse seeds constraint
        account.seeds = self._parse_seeds_constraint(attributes)

        # Parse associated_token constraint
        account.associated_token = self._parse_associated_token_constraint(attributes)

        # Parse custom constraints
        account.custom_constraints = self._parse_custom_constraints(attributes)

        # Parse has_one constraints
        account.has_one = self._parse_has_one_constraints(attributes)

        # Parse other attributes
        for attr in attributes:
            if attr.name == "payer" and attr.value:
                account.payer = attr.value
            elif attr.name == "space" and attr.value:
                account.space = attr.value
            elif attr.name == "address" and attr.value:
                account.address = attr.value

        return account

    def _determine_account_type(self, type_name: str, attributes: List[ConstraintAttribute]) -> AccountType:
        """Determine the account type based on type name and constraints."""
        # Check for associated token constraints
        has_associated_token = any(
            attr.name.startswith("associated_token::") for attr in attributes
        )
        if has_associated_token:
            return AccountType.ASSOCIATED_TOKEN

        # Check for seeds constraint
        has_seeds = any(attr.name == "seeds" for attr in attributes)
        if has_seeds:
            return AccountType.SEEDS_DERIVED

        # Check type name
        if "Signer" in type_name:
            return AccountType.SIGNER
        elif "Program" in type_name:
            return AccountType.PROGRAM
        elif "Interface" in type_name:
            return AccountType.INTERFACE
        elif "Account" in type_name or "AccountInfo" in type_name or "AccountLoader" in type_name:
            return AccountType.BASIC

        return AccountType.UNKNOWN

    def _parse_seeds_constraint(self, attributes: List[ConstraintAttribute]) -> Optional[SeedsConstraint]:
        """Parse seeds-related constraints."""
        seeds_attr = None
        bump_attr = None
        program_attr = None

        for attr in attributes:
            if attr.name == "seeds":
                seeds_attr = attr.value
            elif attr.name == "bump":
                bump_attr = attr.value if attr.value else "bump"
            elif attr.name == "seeds::program":
                program_attr = attr.value

        if seeds_attr is None:
            return None

        # Parse seeds list (it's a Rust array)
        seeds_list = self._parse_seeds_array(seeds_attr)

        return SeedsConstraint(
            seeds=seeds_list,
            bump=bump_attr,
            program=program_attr
        )

    def _parse_seeds_array(self, seeds_str: str) -> List[str]:
        """Parse Rust array of seeds into list of strings."""
        # Remove outer brackets if present
        seeds_str = seeds_str.strip()
        if seeds_str.startswith('[') and seeds_str.endswith(']'):
            seeds_str = seeds_str[1:-1]

        # Split by comma, but be careful with nested brackets
        seeds = self._smart_split(seeds_str, ',')

        return [s.strip() for s in seeds if s.strip()]

    def _parse_associated_token_constraint(self, attributes: List[ConstraintAttribute]) -> Optional[AssociatedTokenConstraint]:
        """Parse associated_token::* constraints."""
        mint = None
        authority = None
        token_program = None

        for attr in attributes:
            if attr.name == "associated_token::mint":
                mint = attr.value
            elif attr.name == "associated_token::authority":
                authority = attr.value
            elif attr.name == "associated_token::token_program":
                token_program = attr.value

        if mint is None and authority is None and token_program is None:
            return None

        return AssociatedTokenConstraint(
            mint=mint,
            authority=authority,
            token_program=token_program
        )

    def _parse_custom_constraints(self, attributes: List[ConstraintAttribute]) -> List[CustomConstraint]:
        """Parse custom constraint expressions."""
        constraints = []

        for attr in attributes:
            if attr.name == "constraint" and attr.value:
                # Check for error code (@ ErrorCode)
                value = attr.value
                error_code = None

                if '@' in value:
                    parts = value.split('@', 1)
                    value = parts[0].strip()
                    error_code = parts[1].strip() if len(parts) > 1 else None

                constraints.append(CustomConstraint(
                    expression=value,
                    error_code=error_code
                ))

        return constraints

    def _parse_has_one_constraints(self, attributes: List[ConstraintAttribute]) -> List[str]:
        """Parse has_one constraints."""
        has_one_accounts = []

        for attr in attributes:
            if attr.name == "has_one" and attr.value:
                # has_one = account_name
                has_one_accounts.append(attr.value)

        return has_one_accounts

    def _extract_attribute_content(self, attr_text: str) -> Optional[str]:
        """Extract content from #[account(...)] handling nested parentheses."""
        # Find #[account(
        start_pattern = "#[account("
        start_idx = attr_text.find(start_pattern)
        if start_idx == -1:
            return None

        # Start after the opening paren
        start_idx += len(start_pattern)

        # Count parentheses to find the matching closing paren
        paren_count = 1
        i = start_idx
        while i < len(attr_text) and paren_count > 0:
            if attr_text[i] == '(':
                paren_count += 1
            elif attr_text[i] == ')':
                paren_count -= 1
            i += 1

        if paren_count != 0:
            return None

        # Extract content between the parens (i-1 is the closing paren)
        return attr_text[start_idx:i-1]

    def _smart_split(self, text: str, delimiter: str) -> List[str]:
        """Split text by delimiter, respecting nested brackets/parens."""
        parts = []
        current = []
        depth = 0
        paren_depth = 0
        angle_depth = 0

        for char in text:
            if char == '[':
                depth += 1
            elif char == ']':
                depth -= 1
            elif char == '(':
                paren_depth += 1
            elif char == ')':
                paren_depth -= 1
            elif char == '<':
                angle_depth += 1
            elif char == '>':
                angle_depth -= 1
            elif char == delimiter and depth == 0 and paren_depth == 0 and angle_depth == 0:
                parts.append(''.join(current))
                current = []
                continue

            current.append(char)

        if current:
            parts.append(''.join(current))

        return parts

    def _extract_inline_comment(self, field_node) -> Optional[str]:
        """Extract inline comment after a field declaration."""
        line_num = field_node.start_point[0]
        if line_num < len(self.source_lines):
            line = self.source_lines[line_num]
            # Look for // comment
            if '//' in line:
                comment_start = line.index('//')
                return line[comment_start + 2:].strip()

        return None

    def _get_node_text(self, node) -> str:
        """Get the text content of a node."""
        return self.source_code[node.start_byte:node.end_byte].decode('utf-8')

    def _find_child_by_type(self, node, child_type: str):
        """Find first child of given type."""
        for child in node.children:
            if child.type == child_type:
                return child
        return None

    def _find_child_by_field(self, node, field_name: str):
        """Find child by field name."""
        return node.child_by_field_name(field_name)


def extract_constraints_from_file(filepath: str) -> List[Constraints]:
    """Convenience function to extract constraints from a file."""
    extractor = ConstraintExtractor(filepath)
    return extractor.extract_all_constraints()


def main():
    """Test the constraint extractor."""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python constraint_extractor.py <rust_file.rs>")
        sys.exit(1)

    filepath = sys.argv[1]

    if not Path(filepath).exists():
        print(f"Error: File '{filepath}' not found")
        sys.exit(1)

    print(f"Extracting constraints from {filepath}...\n")

    constraints_list = extract_constraints_from_file(filepath)

    print(f"Found {len(constraints_list)} constraint struct(s)\n")
    print("=" * 80)

    for constraint in constraints_list:
        print(f"\nStruct: {constraint.name}")
        print(f"Location: {constraint.source_file}:{constraint.line_start}-{constraint.line_end}")

        if constraint.instruction_args:
            print(f"\nInstruction Arguments ({len(constraint.instruction_args)}):")
            for arg in constraint.instruction_args:
                print(f"  - {arg}")

        print(f"\nAccounts ({len(constraint.accounts)}):")
        for account in constraint.accounts:
            print(f"\n  {account.name}: {account.type_name}")
            print(f"    Type: {account.account_type.value}")
            print(f"    Line: {account.line_number}")

            if account.is_mut:
                print(f"    Mutable: yes")
            if account.is_init:
                print(f"    Init: yes")
            if account.is_init_if_needed:
                print(f"    Init if needed: yes")

            if account.seeds:
                print(f"    Seeds: {account.seeds}")

            if account.associated_token:
                print(f"    Associated Token: {account.associated_token}")

            if account.custom_constraints:
                print(f"    Custom Constraints:")
                for c in account.custom_constraints:
                    print(f"      - {c}")

            if account.payer:
                print(f"    Payer: {account.payer}")

            if account.address:
                print(f"    Address: {account.address}")

            refs = account.get_referenced_accounts()
            if refs:
                print(f"    References: {', '.join(refs)}")

            if account.comment:
                print(f"    Comment: {account.comment}")

        print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
