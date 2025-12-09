#!/usr/bin/env python3
"""
Analyze account definitions and create definition graphs.
Identifies which accounts are defined by what and detects undefined/incorrectly defined accounts.
"""

from typing import List, Set, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import re

from constraint_types import (
    Constraints, AccountField, AccountType, InstructionArgument
)


class DefinitionStatus(Enum):
    """Status of account definition."""
    DEFINED = "defined"  # Properly defined
    UNDEFINED = "undefined"  # Not defined by anything
    PARTIALLY_DEFINED = "partially_defined"  # Some constraints but may be incomplete
    INCORRECTLY_DEFINED = "incorrectly_defined"  # Has constraints but they're invalid
    NEEDS_REVIEW = "needs_review"  # Ambiguous, needs manual review


@dataclass
class DefinitionSource:
    """Represents what defines an account."""
    source_type: str
    connection_type: str
    source_name: Optional[str] = None  # Name of the defining entity
    source_field_name: Optional[str] = None
    details: Optional[str] = None  # Additional details

    def __repr__(self):
        output = ""
        output += f"{self.source_type}"
        if self.source_field_name:
            output += "_field"
        if self.source_name:
            output += f":{self.source_name}"
        if self.source_field_name:
            output += f".{self.source_field_name}"
        
        output += f" ({self.connection_type})"
        return output


@dataclass
class AccountDefinition:
    """Analysis result for a single account."""
    account_name: str
    account_type: AccountType
    status: DefinitionStatus
    defined_by: List[DefinitionSource] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    is_inited: bool = False
    line_number: Optional[int] = None

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            "account_name": self.account_name,
            "account_type": self.account_type.value,
            "status": self.status.value,
            "defined_by": [
                {"type": src.source_type, "name": src.source_name, "details": src.details}
                for src in self.defined_by
            ],
            "issues": self.issues,
            "line_number": self.line_number
        }


@dataclass
class DefinitionGraph:
    """Complete definition graph for a constraint struct."""
    struct_name: str
    source_file: str
    accounts: Dict[str, AccountDefinition] = field(default_factory=dict)
    instruction_args: List[str] = field(default_factory=list)
    constants: List[str] = field(default_factory=list)

    # Statistics
    total_accounts: int = 0
    defined_count: int = 0
    undefined_count: int = 0
    needs_review_count: int = 0

    def add_account_definition(self, definition: AccountDefinition):
        """Add an account definition to the graph."""
        self.accounts[definition.account_name] = definition
        self.total_accounts += 1

        if definition.status == DefinitionStatus.DEFINED:
            self.defined_count += 1
        elif definition.status == DefinitionStatus.UNDEFINED:
            self.undefined_count += 1
        elif definition.status in [DefinitionStatus.NEEDS_REVIEW, DefinitionStatus.PARTIALLY_DEFINED, DefinitionStatus.INCORRECTLY_DEFINED]:
            self.needs_review_count += 1

    def get_undefined_accounts(self) -> List[AccountDefinition]:
        """Get all accounts that are undefined or need review."""
        return [
            defn for defn in self.accounts.values()
            if defn.status in [DefinitionStatus.UNDEFINED, DefinitionStatus.NEEDS_REVIEW,
                              DefinitionStatus.PARTIALLY_DEFINED, DefinitionStatus.INCORRECTLY_DEFINED]
        ]

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            "struct_name": self.struct_name,
            "source_file": self.source_file,
            "statistics": {
                "total_accounts": self.total_accounts,
                "defined": self.defined_count,
                "undefined": self.undefined_count,
                "needs_review": self.needs_review_count
            },
            "instruction_args": self.instruction_args,
            "accounts": {name: defn.to_dict() for name, defn in self.accounts.items()}
        }

    def to_json(self, indent=2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class DefinitionAnalyzer:
    """Analyzes account definitions in Anchor constraint structs."""

    def __init__(self, constraints: Constraints):
        self.constraints = constraints
        self.graph = DefinitionGraph(
            struct_name=constraints.name,
            source_file=constraints.source_file or "unknown",
            instruction_args=[arg.name for arg in constraints.instruction_args]
        )
        self.constants_cache = set()

    def analyze(self) -> DefinitionGraph:
        """Perform full analysis of account definitions."""
        # Build a set of known entities that can define accounts
        known_accounts = {acc.name for acc in self.constraints.accounts}
        known_instruction_args = {arg.name for arg in self.constraints.instruction_args}

        # First pass: analyze each account
        for account in self.constraints.accounts:
            definition = self._analyze_account(account, known_accounts, known_instruction_args)
            self.graph.add_account_definition(definition)

        # Second pass: check for reverse definitions
        # (accounts that are defined by being used in seeds of non-init accounts)
        self._analyze_reverse_definitions()

        self.graph.constants = list(self.constants_cache)

        return self.graph

    def _analyze_reverse_definitions(self):
        """
        Second pass to find accounts that are defined by being used in seeds
        or has_one of non-init accounts (reverse definition).
        """
        for account in self.constraints.accounts:
            if account.is_init or account.is_init_if_needed:
                self.graph.accounts[account.name].is_inited = True
                continue

            # Check has_one reverse definitions first (more specific)
            if account.has_one:
                for ref in account.has_one:
                    self._apply_reverse_definition(
                        ref, account.name, "contains_as_has_one",
                        f"Reverse definition: validated by has_one in non-init account '{account.name}'"
                    )

            # Check seeds-based reverse definitions
            if account.seeds and account.account_type != AccountType.ASSOCIATED_TOKEN:
                # Get accounts referenced in seeds, excluding has_one accounts
                refs = account.get_references()

                for ref in refs:
                    self._apply_reverse_definition(
                        ref, account.name, "contains_as_seed",
                        f"Reverse definition: used in seeds of non-init account '{account.name}'"
                    )

    def _apply_reverse_definition(self, ref: str, defining_account: str, connection_type: str, details: str):
        """Apply reverse definition to an account if it's currently undefined."""
        refs = self._extract_references_from_expression(ref)
        for ref in refs:
            ref_account, source_field = ref
            if ref_account == defining_account:
                continue
            
            if ref_account in self.graph.accounts:
                ref_definition = self.graph.accounts[ref_account]

                ref_definition.defined_by.append(DefinitionSource(
                    source_type="account",
                    connection_type=connection_type,
                    source_name=defining_account,
                    source_field_name=source_field,
                    details=details
                ))

                if ref_definition.status == DefinitionStatus.UNDEFINED:
                    ref_definition.status = DefinitionStatus.DEFINED
                    ref_definition.issues = [
                        issue for issue in ref_definition.issues
                        if "not defined" not in issue.lower()
                    ]

                    self.graph.undefined_count -= 1
                    self.graph.defined_count += 1
            else:
                account_definition = self.graph.accounts[defining_account]
                account_definition.issues.append(f'Account {ref_account} for connection {connection_type} wasn\'t found in the graph')

    def _analyze_account(
        self,
        account: AccountField,
        known_accounts: Set[str],
        known_instruction_args: Set[str]
    ) -> AccountDefinition:
        """Analyze a single account's definition."""
        definition = AccountDefinition(
            account_name=account.name,
            account_type=account.account_type,
            status=DefinitionStatus.UNDEFINED,  # Will be updated
            line_number=account.line_number
        )

        # Check if it's a default-defined account (system programs, etc.)
        if account.is_default_defined():
            definition.defined_by.append(DefinitionSource(
                source_type="default",
                connection_type="default",
                source_name=account.name,
                details="System program or standard account"
            ))
            definition.status = DefinitionStatus.DEFINED
            return definition

        # Check if it's defined by an address constraint
        if account.is_defined_by_address():
            definition.defined_by.append(DefinitionSource(
                source_type="address",
                connection_type="address",
                source_name=account.address,
                details="Fixed address constraint"
            ))
            definition.status = DefinitionStatus.DEFINED
            self.constants_cache.add(account.address)
            return definition

        # Check if it's defined by seeds (without init/init_if_needed)
        if account.is_defined_by_seeds():
            self._analyze_seeds_definition(account, definition, known_accounts, known_instruction_args)
            return definition

        # Check if it's an associated token account
        if account.account_type == AccountType.ASSOCIATED_TOKEN:
            self._analyze_associated_token(account, definition, known_accounts)
            return definition

        # Check custom constraints
        if account.custom_constraints:
            self._analyze_custom_constraints(account, definition, known_accounts)
            # If we found definitions from custom constraints, that's good
            if definition.defined_by:
                return definition

        # If account has init or init_if_needed, check if it's properly defined
        if account.is_init or account.is_init_if_needed:
            self._analyze_initialized_account(account, definition, known_accounts, known_instruction_args)
            return definition

        # If we haven't found any definition, mark as undefined
        if not definition.defined_by:
            definition.status = DefinitionStatus.UNDEFINED
            definition.issues.append("Account is not defined by any constraints")

        return definition

    def _analyze_seeds_definition(
        self,
        account: AccountField,
        definition: AccountDefinition,
        known_accounts: Set[str],
        known_instruction_args: Set[str]
    ):
        """Analyze seeds-based definition"""
        if not account.seeds:
            return
        
        all_sources_valid = True
        added_sources = set()  # Track to avoid duplicates

        for seed in account.seeds.seeds:
            # Check if seed references other accounts or instruction args
            refs = self._extract_references_from_expression(seed)

            if not refs:
                # Likely a constant or literal
                source_name = seed[:50].replace('"', '\'')
                definition.defined_by.append(DefinitionSource(
                    source_type="constant",
                    connection_type="seed",
                    source_name=source_name,
                    details="Constant seed value"
                ))
                self.constants_cache.add(source_name)
            else:
                for ref_ in refs:
                    if ref_ in added_sources:
                        continue

                    ref = ref_[0]

                    if ref in known_accounts:
                        definition.defined_by.append(DefinitionSource(
                            source_type="account",
                            connection_type="seed",
                            source_name=ref,
                            source_field_name=ref_[1],
                            details=f"Referenced in seed: {seed[:50]}"
                        ))
                        added_sources.add(ref_)
                    elif ref in known_instruction_args:
                        definition.defined_by.append(DefinitionSource(
                            source_type="instruction_arg",
                            connection_type="seed",
                            source_name=ref,
                            source_field_name=ref_[1],
                            details=f"Referenced in seed: {seed[:50]}"
                        ))
                        added_sources.add(ref_)
                    else:
                        all_sources_valid = False
                        definition.issues.append(f"Unknown reference '{ref}' in seeds")

        # Check bump reference
        bump_refs = self._extract_references_from_expression(account.seeds.bump)
        added_sources = set()

        if not bump_refs:
            # Likely a constant or literal
            source_name = account.seeds.bump[:50].replace('"', '\'')
            definition.defined_by.append(DefinitionSource(
                source_type="constant",
                connection_type="seed_bump",
                source_name=source_name,
                details="Constant seed bump value"
            ))
            self.constants_cache.add(source_name)
        else:
            for ref_ in bump_refs:
                if ref_ in added_sources:
                    continue

                ref = ref_[0]
                if ref == 'bump':
                    continue

                if ref in known_accounts:
                    definition.defined_by.append(DefinitionSource(
                        source_type="account",
                        connection_type="seed_bump",
                        source_name=ref,
                        source_field_name=ref_[1],
                        details=f"Referenced in seed_bump: {seed[:50]}"
                    ))
                    added_sources.add(ref_)
                elif ref in known_instruction_args:
                    definition.defined_by.append(DefinitionSource(
                        source_type="instruction_arg",
                        connection_type="seed_bump",
                        source_name=ref,
                        source_field_name=ref_[1],
                        details=f"Referenced in seed_bump: {seed[:50]}"
                    ))
                    added_sources.add(ref_)
                else:
                    all_sources_valid = False
                    definition.issues.append(f"Unknown reference '{ref}' in seed bump")

        # Determine status
        if definition.defined_by:
            if all_sources_valid:
                definition.status = DefinitionStatus.DEFINED
            else:
                definition.status = DefinitionStatus.NEEDS_REVIEW
        else:
            definition.status = DefinitionStatus.UNDEFINED
            definition.issues.append("Seeds constraint present but no valid sources found")

    def _analyze_associated_token(
        self,
        account: AccountField,
        definition: AccountDefinition,
        known_accounts: Set[str]
    ):
        """Analyze associated token account definition."""
        if not account.associated_token:
            definition.status = DefinitionStatus.INCORRECTLY_DEFINED
            definition.issues.append("Marked as associated token but missing associated_token constraints")
            return

        # Associated token accounts MUST have mint and authority
        if not account.associated_token.mint:
            definition.issues.append("Missing 'associated_token::mint' constraint")
        else:
            mint_ref = account.associated_token.mint
            mint_accounts = self._extract_references_from_expression(mint_ref)

            found_mint = False
            for mint_account_ in mint_accounts:
                mint_account = mint_account_[0]
                if mint_account in known_accounts:
                    definition.defined_by.append(DefinitionSource(
                        source_type="account",
                        connection_type="AT_mint",
                        source_name=mint_account,
                        source_field_name=mint_account_[1],
                        details="Associated token mint"
                    ))
                    found_mint = True
                    break

            if not found_mint:
                definition.issues.append(f"Mint reference '{mint_ref}' not found in accounts")

        if not account.associated_token.authority:
            definition.issues.append("Missing 'associated_token::authority' constraint")
        else:
            authority_ref = account.associated_token.authority
            authority_accounts = self._extract_references_from_expression(authority_ref)

            found_authority = False
            for authority_account_ in authority_accounts:
                authority_account = authority_account_[0]
                if authority_account in known_accounts:
                    definition.defined_by.append(DefinitionSource(
                        source_type="account",
                        connection_type="AT_authority",
                        source_name=authority_account,
                        source_field_name=authority_account_[1],
                        details="Associated token authority"
                    ))
                    found_authority = True
                    break

            if not found_authority:
                definition.issues.append(f"Authority reference '{authority_ref}' not found in accounts")

        # Determine status
        if account.associated_token.is_defined() and len(definition.issues) == 0:
            definition.status = DefinitionStatus.DEFINED
        elif account.associated_token.is_defined():
            definition.status = DefinitionStatus.NEEDS_REVIEW
        else:
            definition.status = DefinitionStatus.INCORRECTLY_DEFINED

    def _analyze_custom_constraints(
        self,
        account: AccountField,
        definition: AccountDefinition,
        known_accounts: Set[str]
    ):
        """Analyze custom constraint definitions."""
        for constraint in account.custom_constraints:
            refs = self._extract_references_from_expression(constraint.expression)

            for ref_ in refs:
                ref = ref_[0]
                if ref in known_accounts and ref != account.name:
                    definition.defined_by.append(DefinitionSource(
                        source_type="account",
                        connection_type="custom",
                        source_name=ref,
                        source_field_name=ref_[1],
                        details=f"Custom constraint: {constraint.expression[:50]}"
                    ))

        if definition.defined_by:
            definition.status = DefinitionStatus.NEEDS_REVIEW
            definition.issues.append("Defined only by custom constraints - needs manual verification")

    def _analyze_initialized_account(
        self,
        account: AccountField,
        definition: AccountDefinition,
        known_accounts: Set[str],
        known_instruction_args: Set[str]
    ):
        """Analyze accounts with init or init_if_needed."""
        # These accounts are being created, so they need seeds or are associated token accounts
        if account.seeds:
            self._analyze_seeds_definition(account, definition, known_accounts, known_instruction_args)
            if definition.status == DefinitionStatus.DEFINED:
                return

        if account.account_type == AccountType.ASSOCIATED_TOKEN:
            self._analyze_associated_token(account, definition, known_accounts)
            if definition.status == DefinitionStatus.DEFINED:
                return

        # If still not defined, it's an issue
        if not definition.defined_by:
            definition.status = DefinitionStatus.INCORRECTLY_DEFINED
            definition.issues.append("Account has init/init_if_needed but no seeds or associated_token constraints")

    def _extract_references_from_expression(self, expression: str) -> Set[Tuple[str, str]]:
        """Extract account/argument references from an expression."""
        # Look for patterns like "account_name", "account_name.field" or "account_name.method()"
        pattern = r'\b([a-z_][a-z0-9_]*)(\.|\n|$|\s)([a-z_][a-z0-9_]*)?'
        matches = re.findall(pattern, expression)

        # Filter out known non-account references and method names
        excluded = {'self', 'ctx', 'Some', 'None', 'Ok', 'Err', 'as_ref', 'to_be_bytes',
                   'key', 'as_bytes', 'clone', 'to_string', 'unwrap', 'expect'}

        # Also filter out if it's part of a chained call like "order.order_hash.as_ref()"
        # In this case we only want "order", not "order_hash"
        result = set()
        for match in matches:
            field = ''
            if match[1] == '.' and match[2] not in excluded:
                field = match[2]
            result.add((match[0], field))

        return result


def save_definition_graph(graph: DefinitionGraph, output_path: str):
    from pathlib import Path

    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        f.write(graph.to_json())
    print(f"Definition graph saved to {output_path}")


def print_analysis_summary(graph: DefinitionGraph):
    print(f"\n{'='*80}")
    print(f"DEFINITION ANALYSIS: {graph.struct_name}")
    print(f"{'='*80}")
    print(f"Source: {graph.source_file}")
    print(f"\nStatistics:")
    print(f"  Total accounts: {graph.total_accounts}")
    print(f"  Properly defined: {graph.defined_count}")
    print(f"  Undefined/Need review: {graph.undefined_count + graph.needs_review_count}")

    if graph.instruction_args:
        print(f"\nInstruction Arguments: {', '.join(graph.instruction_args)}")

    problematic = graph.get_undefined_accounts()
    if problematic:
        print(f"\n⚠️  ACCOUNTS NEEDING MANUAL REVIEW ({len(problematic)}):")
        print(f"{'='*80}")
        for defn in problematic:
            print(f"\n  {defn.account_name} [{defn.status.value}] (line {defn.line_number})")

            if defn.defined_by:
                print(f"    Defined by:")
                for source in defn.defined_by:
                    print(f"      - {source}")
            else:
                print(f"    ❌ Not defined by anything")

            if defn.issues:
                print(f"    Issues:")
                for issue in defn.issues:
                    print(f"      - {issue}")

    print(f"\n✅ PROPERLY DEFINED ACCOUNTS ({graph.defined_count}):")
    print(f"{'='*80}")
    for name, defn in graph.accounts.items():
        if defn.status == DefinitionStatus.DEFINED:
            print(f"\n  {name} (line {defn.line_number})")
            if defn.defined_by:
                print(f"    Defined by:")
                for source in defn.defined_by:
                    print(f"      - {source}")


