#!/usr/bin/env python3

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class AccountType(Enum):
    BASIC = "basic"
    SIGNER = "signer"
    PROGRAM = "program"
    INTERFACE = "interface"
    ASSOCIATED_TOKEN = "associated_token"
    SEEDS_DERIVED = "seeds_derived"
    UNKNOWN = "unknown"


@dataclass
class InstructionArgument:
    name: str
    type_name: str

    def __repr__(self):
        return f"InstructionArgument({self.name}: {self.type_name})"


@dataclass
class ConstraintAttribute:
    name: str
    value: Optional[Any] = None

    def __repr__(self):
        if self.value is None:
            return f"{self.name}"
        return f"{self.name} = {self.value}"


@dataclass
class SeedsConstraint:
    seeds: List[str] = field(default_factory=list)
    bump: Optional[str] = None
    program: Optional[str] = None

    def __repr__(self):
        parts = [f"seeds={self.seeds}"]
        if self.bump:
            parts.append(f"bump={self.bump}")
        if self.program:
            parts.append(f"program={self.program}")
        return f"SeedsConstraint({', '.join(parts)})"


@dataclass
class AssociatedTokenConstraint:
    mint: Optional[str] = None
    authority: Optional[str] = None
    token_program: Optional[str] = None

    def is_defined(self) -> bool:
        return self.mint is not None and self.authority is not None

    def __repr__(self):
        parts = []
        if self.mint:
            parts.append(f"mint={self.mint}")
        if self.authority:
            parts.append(f"authority={self.authority}")
        if self.token_program:
            parts.append(f"token_program={self.token_program}")
        return f"AssociatedTokenConstraint({', '.join(parts)})"


@dataclass
class CustomConstraint:
    expression: str
    error_code: Optional[str] = None

    def __repr__(self):
        if self.error_code:
            return f"constraint = {self.expression} @ {self.error_code}"
        return f"constraint = {self.expression}"


@dataclass
class AccountField:
    name: str
    type_name: str
    account_type: AccountType

    is_mut: bool = False
    is_init: bool = False
    is_init_if_needed: bool = False
    seeds: Optional[SeedsConstraint] = None
    associated_token: Optional[AssociatedTokenConstraint] = None
    custom_constraints: List[CustomConstraint] = field(default_factory=list)
    has_one: List[str] = field(default_factory=list)

    payer: Optional[str] = None
    space: Optional[str] = None
    address: Optional[str] = None

    raw_attributes: List[ConstraintAttribute] = field(default_factory=list)

    line_number: Optional[int] = None
    comment: Optional[str] = None

    def is_default_defined(self) -> bool:
        default_names = {
            'system_program', 'token_program', 'associated_token_program',
            'rent', 'clock', 'recent_slothashes', 'instruction_sysvar_account'
        }
        return self.name in default_names

    def is_defined_by_address(self) -> bool:
        return self.address is not None

    def is_defined_by_seeds(self) -> bool:
        return self.seeds is not None and not self.is_init and not self.is_init_if_needed

    def is_associated_token_defined(self) -> bool:
        return (self.account_type == AccountType.ASSOCIATED_TOKEN and
                self.associated_token is not None and
                self.associated_token.is_defined())

    def get_references(self) -> List[str]:
        references = []
        if self.seeds:
            for seed in self.seeds.seeds:
                references.append(seed)
            if self.seeds.bump:
                references.append(self.seeds.bump)

        if self.associated_token:
            if self.associated_token.mint:
                references.append(self.associated_token.mint)
            if self.associated_token.authority:
                references.append(self.associated_token.authority)
            if self.associated_token.token_program:
                references.append(self.associated_token.token_program)

        for constraint in self.custom_constraints:
            references.extend(constraint.expression)

        references.extend(self.has_one)

        if self.payer:
            references.append(self.payer)

        return list(set(references))

    def __repr__(self):
        parts = [f"{self.name}: {self.type_name}"]
        if self.is_mut:
            parts.append("mut")
        if self.is_init:
            parts.append("init")
        if self.is_init_if_needed:
            parts.append("init_if_needed")
        if self.seeds:
            parts.append(str(self.seeds))
        if self.associated_token:
            parts.append(str(self.associated_token))
        return f"AccountField({', '.join(parts)})"


@dataclass
class Constraints:
    name: str
    instruction_args: List[InstructionArgument] = field(default_factory=list)
    accounts: List[AccountField] = field(default_factory=list)

    source_file: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None

    def get_account(self, name: str) -> Optional[AccountField]:
        for account in self.accounts:
            if account.name == name:
                return account
        return None

    def get_instruction_arg(self, name: str) -> Optional[InstructionArgument]:
        for arg in self.instruction_args:
            if arg.name == name:
                return arg
        return None

    def __repr__(self):
        args_str = f"instruction_args={len(self.instruction_args)}" if self.instruction_args else ""
        accounts_str = f"accounts={len(self.accounts)}"
        parts = [p for p in [args_str, accounts_str] if p]
        return f"Constraints({self.name}, {', '.join(parts)})"