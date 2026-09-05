"""Stable public-API surface snapshot and compatibility diff gate.

Implements the helper described by docs/plans/public-api-surface-snapshot.md:
- prefer structured local sources (OpenAPI, package exports, CLI help, schemas)
- normalize + redact; never store secret-shaped values
- diff baseline vs current; block unapproved public breaks when required
- internal-only changes do not fail the gate
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import textwrap
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from .context import (
    is_secret_env_name,
    redact_structure,
    redact_text,
    scrub_environment,
)
from .storage import atomic_write_json, ensure_private_dir


DEFAULT_BASELINE = Path(".elves") / "api-surface" / "baseline.json"
DEFAULT_CURRENT = Path(".elves") / "api-surface" / "current.json"
DEFAULT_BASE_REFS = ("origin/main", "origin/master", "main", "master")


def _secret_env_values(
    parent_env: Mapping[str, str] | None = None,
) -> frozenset[str]:
    """Exact secret-looking values that must never appear in diagnostics."""
    source = parent_env if parent_env is not None else os.environ
    return frozenset(
        value
        for name, value in source.items()
        if is_secret_env_name(name) and isinstance(value, str) and len(value) >= 8
    )


def _inspection_environment(
    parent_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the minimal environment used by candidate inspection children."""
    scrubbed = scrub_environment(parent_env)
    env = dict(scrubbed.env)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _redact_message(value: object) -> str:
    return redact_text(
        str(value),
        exact_values=_secret_env_values(),
    ).text


def _redact_payload(value: Any) -> Any:
    return redact_structure(value, exact_values=_secret_env_values())


_CLI_INSPECTOR = textwrap.dedent(
    r"""
    import argparse
    import ast
    import dataclasses
    import importlib.util
    import inspect
    import json
    import sys
    import textwrap
    from pathlib import Path

    path = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("_elves_api_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    parser = module.build_parser()

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    def expression(node):
        if node is None:
            return None
        try:
            return ast.unparse(node)
        except Exception:
            return ast.dump(node, annotate_fields=True, include_attributes=False)

    def call_name(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return ""

    def literal_dict_keys(value):
        if not isinstance(value, ast.Dict):
            return set(), False
        keys = {
            key.value
            for key in value.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        # ``**mapping`` and computed keys can contribute unknown top-level
        # names.  A partial key list is useful evidence, but it is not a
        # complete public output contract.
        return keys, all(
            isinstance(key, ast.Constant) and isinstance(key.value, str)
            for key in value.keys
        )

    def callable_output_contract(obj, seen=None):
        # Statically resolve the top-level keys returned by a helper.  Follow
        # direct helper-to-helper calls and simple payload dataflow; unresolved
        # producers make required compatibility fail closed.
        seen = set(seen or set())
        identity = f"{getattr(obj, '__module__', '')}.{getattr(obj, '__qualname__', '')}"
        if identity in seen:
            return set(), False, [f"recursive output producer: {identity}"]
        seen.add(identity)
        try:
            source = textwrap.dedent(inspect.getsource(obj))
            parsed = ast.parse(source)
        except (OSError, TypeError, SyntaxError) as exc:
            return set(), False, [f"uninspectable output producer {identity}: {type(exc).__name__}"]
        function = next(
            (
                node
                for node in parsed.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            None,
        )
        if function is None:
            return set(), False, [f"output producer is not a function: {identity}"]
        namespace = getattr(obj, "__globals__", {})
        assignments = {}
        subscript_keys = {}
        update_keys = {}

        function_nodes = []

        class FunctionBodyVisitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                if node is function:
                    function_nodes.append(node)
                    self.generic_visit(node)

            def visit_AsyncFunctionDef(self, node):
                if node is function:
                    function_nodes.append(node)
                    self.generic_visit(node)

            def generic_visit(self, node):
                if node is not function and isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
                ):
                    return
                function_nodes.append(node)
                super().generic_visit(node)

        FunctionBodyVisitor().visit(function)

        for child in function_nodes:
            if isinstance(child, ast.Assign):
                for target in child.targets:
                    if isinstance(target, ast.Name):
                        assignments.setdefault(target.id, []).append(child.value)
            elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
                assignments.setdefault(child.target.id, []).append(child.value)
            if isinstance(child, (ast.Assign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                    ):
                        subscript_keys.setdefault(target.value.id, set()).add(
                            target.slice.value
                        )
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "update"
                and isinstance(child.func.value, ast.Name)
                and child.args
            ):
                keys, complete = literal_dict_keys(child.args[0])
                update_keys.setdefault(child.func.value.id, set()).update(keys)
                if not complete:
                    assignments.setdefault(child.func.value.id, []).append(child.args[0])

        resolving = set()

        def expression_contract(value):
            if value is None:
                return set(), False, ["return without a JSON object"]
            if isinstance(value, ast.Await):
                return expression_contract(value.value)
            if isinstance(value, ast.Dict):
                keys, complete = literal_dict_keys(value)
                reasons = [] if complete else ["dictionary contains **unknown mapping"]
                return keys, complete, reasons
            if isinstance(value, ast.Name):
                return name_contract(value.id)
            if isinstance(value, ast.IfExp):
                left = expression_contract(value.body)
                right = expression_contract(value.orelse)
                return (
                    left[0] | right[0],
                    left[1] and right[1],
                    left[2] + right[2],
                )
            if isinstance(value, ast.Call):
                if (
                    isinstance(value.func, ast.Name)
                    and value.func.id == "redact_structure"
                    and value.args
                ):
                    # Recursive redaction preserves the public mapping shape.
                    return expression_contract(value.args[0])
                if isinstance(value.func, ast.Name) and value.func.id == "dict":
                    if len(value.args) == 1 and not value.keywords:
                        return expression_contract(value.args[0])
                    keys = {kw.arg for kw in value.keywords if kw.arg}
                    complete = not value.args and all(kw.arg for kw in value.keywords)
                    reasons = [] if complete else ["dict() includes an unknown mapping"]
                    return keys, complete, reasons
                if (
                    isinstance(value.func, ast.Attribute)
                    and value.func.attr == "run"
                    and value.args
                ):
                    # Common ``asyncio.run(helper(...))`` wrapper.
                    return expression_contract(value.args[0])
                if (
                    isinstance(value.func, ast.Attribute)
                    and value.func.attr == "to_dict"
                    and isinstance(value.func.value, ast.Name)
                ):
                    return name_contract(value.func.value.id)
                target = None
                if isinstance(value.func, ast.Name):
                    target = namespace.get(value.func.id)
                if inspect.isfunction(target):
                    return callable_output_contract(target, seen)
                if inspect.isclass(target) and dataclasses.is_dataclass(target):
                    return {field.name for field in dataclasses.fields(target)}, True, []
                return set(), False, [f"unresolved output call: {expression(value)}"]
            return set(), False, [f"unresolved output expression: {expression(value)}"]

        def name_contract(name):
            if name in resolving:
                return set(), False, [f"cyclic payload assignment: {name}"]
            resolving.add(name)
            values = assignments.get(name, [])
            keys = set(subscript_keys.get(name, set())) | set(update_keys.get(name, set()))
            complete = bool(values)
            reasons = []
            for value in values:
                found, resolved, why = expression_contract(value)
                keys.update(found)
                complete = complete and resolved
                reasons.extend(why)
            resolving.remove(name)
            if not values:
                reasons.append(f"payload variable has no local producer: {name}")
            return keys, complete, reasons

        returns = [
            child.value for child in function_nodes if isinstance(child, ast.Return)
        ]
        if not returns:
            return set(), False, [f"output producer has no return: {identity}"]
        keys = set()
        complete = True
        reasons = []
        for value in returns:
            found, resolved, why = expression_contract(value)
            keys.update(found)
            complete = complete and resolved
            reasons.extend(why)
        if not complete:
            try:
                annotation = inspect.signature(obj).return_annotation
            except (TypeError, ValueError):
                annotation = inspect.Signature.empty
            if isinstance(annotation, str):
                annotation = namespace.get(annotation, annotation)
            if inspect.isclass(annotation) and dataclasses.is_dataclass(annotation):
                keys.update(field.name for field in dataclasses.fields(annotation))
                complete = True
                reasons = []
        return keys, complete, sorted(set(reasons))

    def branch_values(value):
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return {value.value}
        if isinstance(value, (ast.Set, ast.Tuple, ast.List)):
            return {
                item.value
                for item in value.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            }
        return set()

    def branch_matches(test, command):
        if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
            return False
        left = test.left
        right = test.comparators[0]
        op = test.ops[0]
        if isinstance(left, ast.Name) and left.id == "action":
            values = branch_values(right)
            return command in values and isinstance(op, (ast.Eq, ast.In))
        if isinstance(right, ast.Name) and right.id == "action":
            values = branch_values(left)
            return command in values and isinstance(op, ast.Eq)
        return False

    def handler_contract(name, command, handler=None):
        node = functions.get(name)
        if node is None and inspect.isfunction(handler):
            # Modular CLI handlers are part of the shipped API. Inspect only
            # source under this CLI's scripts directory, never external plugins.
            try:
                source_path = Path(inspect.getsourcefile(handler)).resolve()
                source_path.relative_to(path.parent)
                parsed = ast.parse(textwrap.dedent(inspect.getsource(handler)))
                node = next((item for item in parsed.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))), None)
            except (OSError, TypeError, ValueError, SyntaxError):
                node = None
        if node is None:
            return {
                "output_calls": [],
                "output_keys": [],
                "output_complete": False,
                "output_incomplete_reasons": [
                    f"handler source is outside inspected CLI module: {name}"
                ],
                "exit_codes": [],
                "dynamic_exit": False,
                "dynamic_exit_expressions": [],
                "exit_expressions": [],
            }
        parents = {
            child: parent
            for parent in ast.walk(node)
            for child in ast.iter_child_nodes(parent)
        }
        matched_branches = [
            child
            for child in ast.walk(node)
            if isinstance(child, ast.If) and branch_matches(child.test, command)
        ]
        if matched_branches:
            # Shared exception JSON is part of each action's contract.  Analyze
            # the selected action bodies without their sibling ``elif`` trees,
            # which prevents one shared handler from contaminating every CLI
            # command with every other branch's output contract.
            matched_bodies = [
                statement
                for branch in matched_branches
                for statement in branch.body
            ]
            enclosing_tries = []
            for branch in matched_branches:
                ancestor = parents.get(branch)
                while ancestor is not None:
                    if isinstance(ancestor, ast.Try) and ancestor not in enclosing_tries:
                        enclosing_tries.append(ancestor)
                    ancestor = parents.get(ancestor)
            exception_bodies = [
                statement
                for enclosing_try in enclosing_tries
                for handler in enclosing_try.handlers
                for statement in handler.body
            ]
            analysis_root = ast.Module(
                body=matched_bodies + exception_bodies,
                type_ignores=[],
            )
        else:
            analysis_root = node
        output_calls = []
        output_names = set()
        output_keys_by_name = {}
        output_values_by_name = {}
        output_expressions = []
        output_literal_variants = []
        direct_output_keys = set()
        exit_codes = set()
        dynamic_exit = False
        dynamic_exit_expressions = set()
        exits = []

        def dict_keys(value):
            return literal_dict_keys(value)[0]

        def assigned_names(target):
            if isinstance(target, ast.Name):
                return [target.id]
            if isinstance(target, (ast.Tuple, ast.List)):
                return [
                    item.id
                    for item in target.elts
                    if isinstance(item, ast.Name)
                ]
            return []

        def block_guarantees_exit(statements):
            # Conservatively prove every path through a helper exits explicitly.
            for statement in statements:
                if isinstance(statement, (ast.Return, ast.Raise)):
                    return True
                if isinstance(statement, ast.If):
                    if (
                        statement.orelse
                        and block_guarantees_exit(statement.body)
                        and block_guarantees_exit(statement.orelse)
                    ):
                        return True
                if isinstance(statement, (ast.With, ast.AsyncWith)):
                    if block_guarantees_exit(statement.body):
                        return True
            return False

        def helper_exit_nodes(function):
            # Collect exits from one function body, excluding nested definitions.
            found = []
            unresolved = False

            class ExitVisitor(ast.NodeVisitor):
                def visit_FunctionDef(self, child):
                    if child is function:
                        self.generic_visit(child)

                def visit_AsyncFunctionDef(self, child):
                    if child is function:
                        self.generic_visit(child)

                def visit_ClassDef(self, child):
                    return

                def visit_Lambda(self, child):
                    return

                def visit_Return(self, child):
                    found.append(("return", child.value))

                def visit_Raise(self, child):
                    nonlocal unresolved
                    if (
                        isinstance(child.exc, ast.Call)
                        and call_name(child.exc.func) == "SystemExit"
                    ):
                        if len(child.exc.args) == 1:
                            found.append(("raise", child.exc.args[0]))
                        elif not child.exc.args:
                            found.append(("raise", ast.Constant(value=0)))
                        else:
                            unresolved = True
                    else:
                        unresolved = True

                def visit_Yield(self, child):
                    nonlocal unresolved
                    unresolved = True

                def visit_YieldFrom(self, child):
                    nonlocal unresolved
                    unresolved = True

            ExitVisitor().visit(function)
            return found, unresolved

        def literal_exit_codes(value, seen_helpers=None):
            seen_helpers = frozenset(seen_helpers or ())
            if isinstance(value, ast.Constant) and isinstance(value.value, int) and not isinstance(
                value.value, bool
            ):
                return {value.value}, False
            if (
                isinstance(value, ast.UnaryOp)
                and isinstance(value.op, ast.USub)
                and isinstance(value.operand, ast.Constant)
                and isinstance(value.operand.value, int)
            ):
                return {-value.operand.value}, False
            if isinstance(value, ast.Await):
                return literal_exit_codes(value.value, seen_helpers)
            if isinstance(value, ast.IfExp):
                left, left_dynamic = literal_exit_codes(value.body, seen_helpers)
                right, right_dynamic = literal_exit_codes(value.orelse, seen_helpers)
                return left | right, left_dynamic or right_dynamic
            if isinstance(value, ast.Call):
                target_name = call_name(value.func)
                if target_name == "_emit_json":
                    exit_values = [
                        keyword.value
                        for keyword in value.keywords
                        if keyword.arg == "exit_code"
                    ]
                    if len(exit_values) != 1:
                        return set(), True
                    return literal_exit_codes(exit_values[0], seen_helpers)
                if isinstance(value.func, ast.Name) and target_name in functions:
                    return helper_exit_codes(target_name, seen_helpers)
            return set(), value is not None

        def helper_exit_codes(helper_name, seen_helpers):
            # Resolve a direct local helper's literal process-exit contract.
            if helper_name in seen_helpers:
                return set(), True
            helper = functions.get(helper_name)
            if (
                helper is None
                or isinstance(helper, ast.AsyncFunctionDef)
                or helper.decorator_list
                or not block_guarantees_exit(helper.body)
            ):
                return set(), True
            nested_seen = frozenset((*seen_helpers, helper_name))
            exits_found, unresolved = helper_exit_nodes(helper)
            if not exits_found:
                return set(), True
            known = set()
            dynamic = unresolved
            for _kind, exit_value in exits_found:
                resolved, unresolved = literal_exit_codes(
                    exit_value,
                    nested_seen,
                )
                known.update(resolved)
                dynamic = dynamic or unresolved
            return known, dynamic

        # First pass: map simple payload variables to their declared top-level
        # JSON keys.  This deliberately does not collect every dict literal in
        # the handler: internal bookkeeping dictionaries are not public output.
        for child in ast.walk(analysis_root):
            if isinstance(child, ast.Assign):
                keys = dict_keys(child.value)
                for target in child.targets:
                    for assigned in assigned_names(target):
                        output_values_by_name.setdefault(assigned, []).append(child.value)
                        if keys:
                            output_keys_by_name.setdefault(assigned, set()).update(keys)
            elif isinstance(child, ast.AnnAssign):
                keys = dict_keys(child.value)
                for assigned in assigned_names(child.target):
                    output_values_by_name.setdefault(assigned, []).append(child.value)
                    if keys:
                        output_keys_by_name.setdefault(assigned, set()).update(keys)
            if isinstance(child, (ast.Assign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and isinstance(target.slice, ast.Constant)
                        and isinstance(target.slice.value, str)
                    ):
                        output_keys_by_name.setdefault(target.value.id, set()).add(
                            target.slice.value
                        )

        for child in ast.walk(analysis_root):
            if isinstance(child, ast.Call) and call_name(child.func) in {"print", "_emit_json"}:
                output_calls.append(
                    {
                        "call": call_name(child.func),
                        "args": [expression(arg) for arg in child.args],
                        "keywords": sorted(
                            (kw.arg or "**", expression(kw.value)) for kw in child.keywords
                        ),
                    }
                )
                output_call = call_name(child.func)
                static_keys = {
                    kw.arg
                    for kw in child.keywords
                    if output_call == "_emit_json"
                    and kw.arg not in {None, "exit_code"}
                }
                for arg in child.args:
                    output_expressions.append(
                        (arg, output_call == "_emit_json", static_keys)
                    )
                    if isinstance(arg, ast.Name):
                        output_names.add(arg.id)
                    direct_output_keys.update(dict_keys(arg))
                if call_name(child.func) == "_emit_json":
                    for kw in child.keywords:
                        if kw.arg == "exit_code":
                            exits.append(expression(kw.value))
                            known, is_dynamic = literal_exit_codes(kw.value)
                            exit_codes.update(known)
                            dynamic_exit = dynamic_exit or is_dynamic
                            if is_dynamic:
                                dynamic_exit_expressions.add(expression(kw.value))
                        elif kw.arg is None:
                            output_expressions.append((kw.value, True, static_keys))
                        else:
                            direct_output_keys.add(kw.arg)
                    if not child.args and not any(kw.arg is None for kw in child.keywords):
                        output_literal_variants.append(static_keys)
            if isinstance(child, ast.Return):
                exits.append(expression(child.value))
                # A return of _emit_json is accounted for by its exit_code
                # keyword above.  Other returns are the command's text-mode
                # process exit contract.
                if not (
                    isinstance(child.value, ast.Call)
                    and call_name(child.value.func) == "_emit_json"
                ):
                    known, is_dynamic = literal_exit_codes(child.value)
                    exit_codes.update(known)
                    dynamic_exit = dynamic_exit or is_dynamic
                    if is_dynamic:
                        dynamic_exit_expressions.add(expression(child.value))
            if (
                isinstance(child, ast.Raise)
                and isinstance(child.exc, ast.Call)
                and call_name(child.exc.func) == "SystemExit"
            ):
                exits.extend(expression(arg) for arg in child.exc.args)
                for arg in child.exc.args:
                    known, is_dynamic = literal_exit_codes(arg)
                    exit_codes.update(known)
                    dynamic_exit = dynamic_exit or is_dynamic
                    if is_dynamic:
                        dynamic_exit_expressions.add(expression(arg))
        resolving_output_names = set()

        def resolve_output(value, *, json_required=False):
            if isinstance(value, (ast.Constant, ast.JoinedStr)):
                return set(), True, []
            if isinstance(value, ast.Dict):
                keys, complete = literal_dict_keys(value)
                reasons = [] if complete else ["output dictionary contains **unknown mapping"]
                return keys, complete, reasons
            if isinstance(value, ast.Name):
                name = value.id
                if name in resolving_output_names:
                    return set(), False, [f"cyclic handler output assignment: {name}"]
                resolving_output_names.add(name)
                producers = output_values_by_name.get(name, [])
                keys = set(output_keys_by_name.get(name, set()))
                complete = bool(producers)
                reasons = []
                for producer in producers:
                    found, resolved, why = resolve_output(
                        producer,
                        json_required=json_required,
                    )
                    keys.update(found)
                    complete = complete and resolved
                    reasons.extend(why)
                resolving_output_names.remove(name)
                if not producers:
                    reasons.append(f"printed output variable has no local producer: {name}")
                return keys, complete, reasons
            if isinstance(value, ast.IfExp):
                left = resolve_output(value.body, json_required=json_required)
                right = resolve_output(value.orelse, json_required=json_required)
                return left[0] | right[0], left[1] and right[1], left[2] + right[2]
            if isinstance(value, ast.Await):
                return resolve_output(value.value, json_required=json_required)
            if isinstance(value, ast.Call):
                # Serialization/execution wrappers preserve the wrapped payload.
                if (
                    isinstance(value.func, ast.Name)
                    and value.func.id == "redact_structure"
                    and value.args
                ):
                    return resolve_output(value.args[0], json_required=json_required)
                if (
                    isinstance(value.func, ast.Attribute)
                    and value.func.attr == "dumps"
                    and value.args
                ):
                    return resolve_output(value.args[0], json_required=True)
                if (
                    isinstance(value.func, ast.Attribute)
                    and value.func.attr == "run"
                    and value.args
                ):
                    return resolve_output(
                        value.args[0],
                        json_required=json_required,
                    )
                if isinstance(value.func, ast.Name) and value.func.id in {"dict", "asdict"}:
                    if value.func.id == "dict":
                        if len(value.args) == 1 and not value.keywords:
                            return resolve_output(value.args[0], json_required=True)
                        keys = {kw.arg for kw in value.keywords if kw.arg}
                        complete = not value.args and all(kw.arg for kw in value.keywords)
                        reasons = [] if complete else ["dict() output includes unknown mapping"]
                        return keys, complete, reasons
                    if value.args:
                        return resolve_output(value.args[0], json_required=True)
                if (
                    isinstance(value.func, ast.Attribute)
                    and value.func.attr == "to_dict"
                ):
                    return resolve_output(value.func.value, json_required=True)
                if isinstance(value.func, ast.Name):
                    target = getattr(module, value.func.id, None)
                    if inspect.isfunction(target):
                        return callable_output_contract(target)
                    if inspect.isclass(target) and dataclasses.is_dataclass(target):
                        return {field.name for field in dataclasses.fields(target)}, True, []
                    return set(), False, [f"unresolved output helper: {value.func.id}"]
                return set(), False, [f"unresolved output call: {expression(value)}"]
            if isinstance(value, ast.BinOp) and isinstance(value.op, ast.BitOr):
                left = resolve_output(value.left, json_required=True)
                right = resolve_output(value.right, json_required=True)
                return left[0] | right[0], left[1] and right[1], left[2] + right[2]
            # Formatting, attribute access, and indexing can be complete text
            # output, but are not a statically known JSON object contract.
            if isinstance(value, (ast.BinOp, ast.FormattedValue, ast.Subscript, ast.Attribute)):
                if json_required:
                    return set(), False, [
                        f"unresolved JSON handler output: {expression(value)}"
                    ]
                return set(), True, []
            return set(), False, [f"unresolved handler output: {expression(value)}"]

        output_keys = set(direct_output_keys)
        output_complete = True
        output_incomplete_reasons = []
        output_variants = [
            {"json": True, "keys": sorted(keys)}
            for keys in output_literal_variants
        ]
        for output_value, json_required, static_keys in output_expressions:
            found, complete, reasons = resolve_output(
                output_value,
                json_required=json_required,
            )
            found.update(static_keys)
            output_keys.update(found)
            output_complete = output_complete and complete
            output_incomplete_reasons.extend(reasons)
            if json_required or found:
                output_variants.append(
                    {"json": bool(json_required or found), "keys": sorted(found)}
                )
        return {
            "output_calls": sorted(
                output_calls,
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            ),
            "output_keys": sorted(output_keys),
            "output_variants": sorted(
                output_variants,
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            ),
            "output_complete": output_complete,
            "output_incomplete_reasons": sorted(set(output_incomplete_reasons)),
            "exit_codes": sorted(exit_codes),
            "dynamic_exit": dynamic_exit,
            "dynamic_exit_expressions": sorted(dynamic_exit_expressions),
            "exit_expressions": sorted({item for item in exits if item is not None}),
        }

    def stable_value(value):
        if value is argparse.SUPPRESS:
            return "SUPPRESS"
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (list, tuple)):
            return [stable_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): stable_value(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if callable(value):
            return getattr(value, "__name__", type(value).__name__)
        return f"<{type(value).__module__}.{type(value).__qualname__}>"

    def action_contract(action):
        choices = action.choices
        if isinstance(choices, dict):
            choices = sorted(str(choice) for choice in choices)
        elif choices is not None:
            choices = [stable_value(choice) for choice in choices]
        return {
            "action": type(action).__name__,
            "choices": choices,
            "const": stable_value(getattr(action, "const", None)),
            "default": stable_value(action.default),
            "dest": action.dest,
            "flags": list(action.option_strings),
            "help": None if action.help is argparse.SUPPRESS else action.help,
            "nargs": stable_value(action.nargs),
            "required": bool(getattr(action, "required", False)),
            "type": stable_value(action.type),
        }

    contracts = []

    def walk(current, path_parts):
        subcommands = []
        arguments = []
        child_parsers = []
        for action in current._actions:
            if isinstance(action, argparse._SubParsersAction):
                subcommands.extend(sorted(action.choices))
                child_parsers.extend(sorted(action.choices.items()))
            else:
                arguments.append(action_contract(action))
        mutually_exclusive_groups = []
        for group in current._mutually_exclusive_groups:
            members = sorted(
                [
                    {
                        "dest": action.dest,
                        "flags": sorted(action.option_strings),
                    }
                    for action in group._group_actions
                    if getattr(action, "dest", None)
                ],
                key=lambda item: (item["dest"], item["flags"]),
            )
            if members:
                mutually_exclusive_groups.append(
                    {"members": members, "required": bool(group.required)}
                )
        handler = current.get_default("func")
        handler_name = getattr(handler, "__name__", None)
        command = str(path_parts[-1]) if path_parts else ""
        contracts.append(
            {
                    "arguments": sorted(
                        arguments,
                        key=lambda item: (item["dest"], item["flags"]),
                    ),
                    "description": current.description,
                    "epilog": current.epilog,
                    "handler": handler_name,
                    "handler_contract": (
                        handler_contract(handler_name, command, handler) if handler_name else None
                    ),
                    "help": current.description,
                    "mutually_exclusive_groups": sorted(
                        mutually_exclusive_groups,
                        key=lambda item: json.dumps(
                            item,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    ),
                    "path": path_parts,
                    "root": not path_parts,
                    "subcommands": sorted(set(subcommands)),
            }
        )
        for command, child in child_parsers:
            walk(child, path_parts + [command])

    walk(parser, [])
    print(json.dumps(contracts, sort_keys=True, separators=(",", ":")))
    """
)


_EXPORT_INSPECTOR = textwrap.dedent(
    r"""
    import dataclasses
    import enum
    import importlib
    import inspect
    import json
    import sys
    from pathlib import Path

    root = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(root / "scripts"))
    module = importlib.import_module("cobbler_runtime")

    def stable_value(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (list, tuple, set, frozenset)):
            items = [stable_value(item) for item in value]
            if isinstance(value, (set, frozenset)):
                items.sort(key=lambda item: json.dumps(item, sort_keys=True))
            return items
        if isinstance(value, dict):
            return {
                str(key): stable_value(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        return f"<{type(value).__module__}.{type(value).__qualname__}>"

    def signature(value):
        try:
            return str(inspect.signature(value))
        except (TypeError, ValueError):
            return None

    contracts = []
    for name in sorted(getattr(module, "__all__", ())):
        if not hasattr(module, name):
            contracts.append({"name": name, "missing": True})
            continue
        value = getattr(module, name)
        if inspect.isfunction(value) or inspect.isbuiltin(value):
            contract = {
                "kind": "function",
                "signature": signature(value),
            }
        elif inspect.isclass(value):
            methods = {}
            properties = {}
            for member_name, raw_member in vars(value).items():
                if member_name.startswith("_"):
                    continue
                member = raw_member
                if isinstance(raw_member, (staticmethod, classmethod)):
                    member = raw_member.__func__
                if inspect.isfunction(member) or inspect.isbuiltin(member):
                    methods[member_name] = signature(member)
                elif isinstance(raw_member, property):
                    properties[member_name] = {
                        "getter": signature(raw_member.fget) if raw_member.fget else None,
                        "setter": signature(raw_member.fset) if raw_member.fset else None,
                    }
            contract = {
                "kind": "class",
                "signature": signature(value),
                "methods": methods,
                "properties": properties,
            }
            if dataclasses.is_dataclass(value):
                contract["dataclass_fields"] = [
                    {
                        "name": field.name,
                        "type": str(field.type),
                        "default": (
                            "<required>"
                            if field.default is dataclasses.MISSING
                            and field.default_factory is dataclasses.MISSING
                            else stable_value(field.default)
                            if field.default is not dataclasses.MISSING
                            else "<factory>"
                        ),
                        "init": field.init,
                        "kw_only": getattr(field, "kw_only", False),
                    }
                    for field in dataclasses.fields(value)
                ]
            if issubclass(value, enum.Enum):
                contract["enum_members"] = {
                    member_name: stable_value(member.value)
                    for member_name, member in value.__members__.items()
                }
        else:
            contract = {
                "kind": "constant",
                "type": f"{type(value).__module__}.{type(value).__qualname__}",
                "value": stable_value(value),
            }
        contracts.append({"name": name, "contract": contract})
    print(json.dumps(contracts, sort_keys=True, separators=(",", ":")))
    """
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class SurfaceEntry:
    kind: str  # rest | export | cli | schema | config
    name: str
    signature: str
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ApiSnapshot:
    status: str  # captured | degraded | unavailable
    captured_at: str
    source: str
    entries: list[SurfaceEntry] = field(default_factory=list)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "captured_at": self.captured_at,
            "source": self.source,
            "reason": self.reason,
            "entries": [e.to_dict() for e in self.entries],
            "digest": self.digest(),
        }

    def digest(self) -> str:
        material = json.dumps(
            sorted(
                (
                    e.kind,
                    e.name,
                    e.signature,
                )
                for e in self.entries
            ),
            sort_keys=True,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


_CONTRACT_ANNOTATION_KEYS = frozenset(
    {
        "$comment",
        "description",
        "example",
        "examples",
        "externalDocs",
        "markdownDescription",
        "summary",
        "title",
    }
)
_OPENAPI_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)


_CONTRACT_MEMBER_NAME_CONTAINERS = frozenset(
    {
        "$defs",
        "callbacks",
        "content",
        "definitions",
        "dependencies",
        "dependentRequired",
        "dependentSchemas",
        "encoding",
        "headers",
        "links",
        "mapping",
        "properties",
        "patternProperties",
    }
)
_CONTRACT_SET_LIKE_ARRAYS = frozenset({"enum", "required", "type"})


def _canonical_contract(value: Any, *, parent_key: str | None = None) -> Any:
    """Return a deterministic structural contract without prose/examples."""
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_contract(item, parent_key=str(key))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not (
                parent_key not in _CONTRACT_MEMBER_NAME_CONTAINERS
                and str(key) in _CONTRACT_ANNOTATION_KEYS
            )
        }
    if isinstance(value, list):
        items = [_canonical_contract(item, parent_key=parent_key) for item in value]
        if parent_key in _CONTRACT_SET_LIKE_ARRAYS:
            return sorted(
                items,
                key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
            )
        return items
    return value


def _contract_signature(value: Any) -> str:
    return json.dumps(
        _canonical_contract(value),
        sort_keys=True,
        separators=(",", ":"),
    )


def _snapshot_openapi(repo_root: Path) -> tuple[list[SurfaceEntry], list[str]]:
    entries: list[SurfaceEntry] = []
    issues: list[str] = []
    candidates = [
        "openapi.json",
        "openapi.yaml",
        "swagger.json",
        "docs/openapi.json",
        "references/implement-done-report.schema.json",
    ]
    for rel in candidates:
        path = repo_root / rel
        if not path.is_file():
            continue
        if path.suffix != ".json":
            issues.append(f"unsupported structured contract format: {rel}")
            continue
        data = _load_json(path)
        if data is None:
            issues.append(f"invalid JSON contract: {rel}")
            continue
        if isinstance(data, dict) and "paths" in data:
            document_contract = {
                key: value
                for key, value in data.items()
                if key
                not in {
                    "components",
                    "definitions",
                    "externalDocs",
                    "info",
                    "openapi",
                    "parameters",
                    "paths",
                    "responses",
                    "securityDefinitions",
                    "swagger",
                    "tags",
                }
            }
            if document_contract:
                entries.append(
                    SurfaceEntry(
                        kind="rest",
                        name=f"{rel}#document",
                        signature=_contract_signature(document_contract),
                        meta={"source": rel},
                    )
                )
            paths = data.get("paths")
            if not isinstance(paths, Mapping):
                issues.append(f"malformed OpenAPI paths: {rel}")
                continue
            for route, path_item in sorted(paths.items()):
                if not isinstance(path_item, Mapping):
                    issues.append(f"malformed OpenAPI path item: {rel}:{route}")
                    continue
                path_parameters = path_item.get("parameters") or []
                if not isinstance(path_parameters, list):
                    issues.append(f"malformed OpenAPI path parameters: {rel}:{route}")
                    path_parameters = []
                path_contract = {
                    key: value
                    for key, value in path_item.items()
                    if str(key).lower() not in _OPENAPI_METHODS
                }
                entries.append(
                    SurfaceEntry(
                        kind="rest",
                        name=f"{rel}#PATH {route}",
                        signature=_contract_signature(path_contract),
                        meta={"source": rel},
                    )
                )
                for method, operation in sorted(path_item.items()):
                    if str(method).lower() not in _OPENAPI_METHODS:
                        continue
                    if not isinstance(operation, Mapping):
                        issues.append(
                            f"malformed OpenAPI operation: {rel}:{method.upper()} {route}"
                        )
                        continue
                    signature = {
                        "method": str(method).upper(),
                        "path": str(route),
                        "path_parameters": path_parameters,
                        "operation": operation,
                    }
                    entries.append(
                        SurfaceEntry(
                            kind="rest",
                            name=f"{rel}#{str(method).upper()} {route}",
                            signature=_contract_signature(signature),
                            meta={"source": rel},
                        )
                    )
            components = data.get("components")
            if components is not None and not isinstance(components, Mapping):
                issues.append(f"malformed OpenAPI components: {rel}")
            elif isinstance(components, Mapping):
                for category, members in sorted(components.items()):
                    if not isinstance(members, Mapping):
                        issues.append(
                            f"malformed OpenAPI components category: {rel}:{category}"
                        )
                        continue
                    for name, contract in sorted(members.items()):
                        if not isinstance(contract, Mapping):
                            issues.append(
                                f"malformed OpenAPI component: {rel}:{category}/{name}"
                            )
                            continue
                        entries.append(
                            SurfaceEntry(
                                kind="schema",
                                name=f"{rel}#/components/{category}/{name}",
                                signature=_contract_signature(contract),
                                meta={"source": rel},
                            )
                        )
            for category in ("definitions", "parameters", "responses", "securityDefinitions"):
                if category not in data:
                    continue
                members = data.get(category)
                if not isinstance(members, Mapping):
                    issues.append(f"malformed Swagger {category}: {rel}")
                    continue
                for name, contract in sorted(members.items()):
                    if not isinstance(contract, Mapping):
                        issues.append(f"malformed Swagger {category} member: {rel}:{name}")
                        continue
                    entries.append(
                        SurfaceEntry(
                            kind="schema" if category == "definitions" else "rest",
                            name=f"{rel}#/{category}/{name}",
                            signature=_contract_signature(contract),
                            meta={"source": rel},
                        )
                    )
        elif isinstance(data, dict) and data.get("$schema"):
            entries.append(
                SurfaceEntry(
                    kind="schema",
                    name=rel,
                    signature=_contract_signature(data),
                    meta={"source": rel},
                )
            )
        else:
            issues.append(f"unrecognized structured contract: {rel}")
    return entries, issues


def _snapshot_python_exports(repo_root: Path) -> tuple[list[SurfaceEntry], list[str]]:
    entries: list[SurfaceEntry] = []
    issues: list[str] = []
    init_path = repo_root / "scripts" / "cobbler_runtime" / "__init__.py"
    if not init_path.is_file():
        return entries, issues
    text = init_path.read_text(encoding="utf-8")
    match = re.search(r"__all__\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if not match:
        return entries, ["cobbler_runtime exports do not declare a static __all__ list"]
    expected_names = sorted(re.findall(r'["\']([^"\']+)["\']', match.group(1)))
    proc = subprocess.run(
        [sys.executable, "-c", _EXPORT_INSPECTOR, str(repo_root)],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
        env=_inspection_environment(),
    )
    if proc.returncode != 0:
        detail = _redact_message(proc.stderr or proc.stdout).strip()
        return entries, [f"Python export inspection failed: {detail[:300]}"]
    try:
        contracts = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return entries, [f"Python export inspection emitted invalid JSON: {exc}"]
    if not isinstance(contracts, list):
        return entries, ["Python export inspection emitted a non-list contract"]
    observed_names: list[str] = []
    for item in contracts:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            issues.append("Python export inspection emitted a malformed entry")
            continue
        name = str(item["name"])
        observed_names.append(name)
        contract = item.get("contract")
        if item.get("missing") is True or not isinstance(contract, Mapping):
            issues.append(f"Python export is missing or uninspectable: {name}")
            continue
        entries.append(
            SurfaceEntry(
                kind="export",
                name=f"cobbler_runtime.{name}",
                signature=json.dumps(contract, sort_keys=True, separators=(",", ":")),
                meta={
                    "source": "scripts/cobbler_runtime/__init__.py",
                    "inspection": "runtime-signature",
                },
            )
        )
    if observed_names != expected_names:
        issues.append(
            "Python export inspection did not match __all__: "
            f"expected={expected_names!r} observed={observed_names!r}"
        )
    return entries, issues


def _snapshot_cli_help(repo_root: Path) -> list[SurfaceEntry]:
    """Capture CLI hierarchy and user-facing argparse/handler contracts.

    The parser is inspected in a separate Python process so capturing a baseline
    checkout cannot pollute this process's imports.  Static command discovery is
    retained as a compatibility fallback for partial/synthetic source trees.
    """
    path = repo_root / "scripts" / "cobbler_agents.py"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-c", _CLI_INSPECTOR, str(path)],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
        env=_inspection_environment(),
    )
    if proc.returncode == 0:
        try:
            contracts = json.loads(proc.stdout)
        except json.JSONDecodeError:
            contracts = None
        if isinstance(contracts, list):
            entries: list[SurfaceEntry] = []
            for contract in contracts:
                if not isinstance(contract, dict):
                    continue
                path_parts = contract.get("path")
                if not isinstance(path_parts, list):
                    continue
                command_path = " ".join(str(part) for part in path_parts)
                entry_name = (
                    f"cobbler_agents {command_path}" if command_path else "cobbler_agents"
                )
                entries.append(
                    SurfaceEntry(
                        kind="cli",
                        name=entry_name,
                        signature=json.dumps(
                            contract,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        meta={
                            "source": "scripts/cobbler_agents.py",
                            "inspection": "argparse+handler-ast",
                        },
                    )
                )
            if entries:
                return entries

    # A deliberately small fallback keeps snapshotting useful in source-only
    # fixtures while marking that full option/output inspection was unavailable.
    commands = sorted(set(re.findall(r'add_parser\(\s*["\']([^"\']+)["\']', text)))
    return [
        SurfaceEntry(
            kind="cli",
            name=f"cobbler_agents {command}",
            signature=json.dumps(
                {
                    "inspection": "static-command-fallback",
                    "path": [command],
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            meta={
                "source": "scripts/cobbler_agents.py",
                "inspection": "static-command-fallback",
            },
        )
        for command in commands
    ]


def _redact_surface_entries(
    entries: Sequence[SurfaceEntry],
    *,
    exact_values: frozenset[str],
) -> tuple[list[SurfaceEntry], list[str]]:
    """Redact persisted entry content and fail closed on identity collapse.

    Entry names are part of the snapshot payload, just like signatures and
    metadata.  Two distinct names can become the same public identity after
    redaction (for example, routes containing different provider tokens).  In
    that case retaining either contract would make the result order-dependent,
    so omit the entire collided identity and degrade the capture.
    """
    cleaned: list[tuple[str, SurfaceEntry]] = []
    original_names: dict[tuple[str, str], set[str]] = {}
    for entry in entries:
        name = redact_text(entry.name, exact_values=exact_values).text
        meta = redact_structure(entry.meta, exact_values=exact_values)
        signature = redact_text(entry.signature, exact_values=exact_values).text
        redacted_entry = SurfaceEntry(
            kind=entry.kind,
            name=name,
            signature=signature,
            meta=dict(meta),
        )
        identity = (redacted_entry.kind, redacted_entry.name)
        original_names.setdefault(identity, set()).add(entry.name)
        cleaned.append((entry.name, redacted_entry))

    collisions = {
        identity
        for identity, names in original_names.items()
        if len(names) > 1
    }
    safe_entries = [
        entry
        for _original_name, entry in cleaned
        if (entry.kind, entry.name) not in collisions
    ]
    issues = [
        f"public surface identity collision after redaction: {kind}:{name}"
        for kind, name in sorted(collisions)
    ]
    return safe_entries, issues


def capture_snapshot(repo_root: Path) -> ApiSnapshot:
    root = Path(repo_root).resolve()
    entries: list[SurfaceEntry] = []
    sources: list[str] = []
    issues: list[str] = []

    contract_entries, contract_issues = _snapshot_openapi(root)
    if contract_entries:
        entries.extend(contract_entries)
        sources.append("openapi/schema")
    issues.extend(contract_issues)

    export_entries, export_issues = _snapshot_python_exports(root)
    if export_entries:
        entries.extend(export_entries)
        sources.append("python_exports")
    issues.extend(export_issues)

    cli_entries = _snapshot_cli_help(root)
    if cli_entries:
        entries.extend(cli_entries)
        sources.append("cli")
    elif (root / "scripts" / "cobbler_agents.py").is_file():
        issues.append("CLI inspection produced no command contracts")
    for entry in cli_entries:
        if entry.meta.get("inspection") == "static-command-fallback":
            issues.append(f"CLI inspection fell back to command names: {entry.name}")
            continue
        try:
            contract = json.loads(entry.signature)
        except json.JSONDecodeError:
            issues.append(f"CLI inspection emitted invalid JSON: {entry.name}")
            continue
        if not isinstance(contract, Mapping):
            issues.append(f"CLI inspection emitted malformed contract: {entry.name}")
            continue
        handler = contract.get("handler_contract") if isinstance(contract, dict) else None
        subcommands = contract.get("subcommands")
        if handler is None and not subcommands:
            issues.append(f"CLI leaf command has no inspectable handler: {entry.name}")
            continue
        if isinstance(handler, Mapping) and handler.get("output_complete") is False:
            reasons = handler.get("output_incomplete_reasons") or []
            detail = f" ({'; '.join(str(item) for item in reasons[:3])})" if reasons else ""
            issues.append(f"CLI output inspection incomplete: {entry.name}{detail}")
    safe_issues = [_redact_message(issue) for issue in issues]
    if not entries:
        return ApiSnapshot(
            status="degraded" if safe_issues else "unavailable",
            captured_at=_utc_now(),
            source="none",
            reason=(
                "; ".join(safe_issues)
                if safe_issues
                else "no structured public surface sources found"
            ),
        )
    # Redact any accidental secret-shaped values in names/signatures/meta.
    exact_values = _secret_env_values()
    cleaned, collision_issues = _redact_surface_entries(
        entries,
        exact_values=exact_values,
    )
    safe_issues.extend(_redact_message(issue) for issue in collision_issues)
    return ApiSnapshot(
        status="degraded" if safe_issues else "captured",
        captured_at=_utc_now(),
        source="+".join(sources),
        entries=cleaned,
        reason="; ".join(safe_issues) if safe_issues else None,
    )


def write_snapshot(path: Path, snapshot: ApiSnapshot) -> Path:
    ensure_private_dir(path.parent)
    atomic_write_json(path, snapshot.to_dict())
    return path


def _snapshot_from_data(data: Any) -> ApiSnapshot | None:
    if not isinstance(data, dict):
        return None
    entries = [
        SurfaceEntry(
            kind=str(e.get("kind")),
            name=str(e.get("name")),
            signature=str(e.get("signature")),
            meta=dict(e.get("meta") or {}),
        )
        for e in (data.get("entries") or [])
        if isinstance(e, dict)
    ]
    return ApiSnapshot(
        status=str(data.get("status") or "unavailable"),
        captured_at=str(data.get("captured_at") or ""),
        source=str(data.get("source") or ""),
        entries=entries,
        reason=data.get("reason"),
    )


def load_snapshot(path: Path) -> ApiSnapshot | None:
    return _snapshot_from_data(_load_json(path))


def _snapshot_completeness_issues(snapshot: ApiSnapshot) -> list[str]:
    issues: list[str] = []
    if snapshot.status != "captured":
        issues.append(snapshot.reason or f"snapshot status is {snapshot.status}")
    if not snapshot.source:
        issues.append("snapshot source is missing")
    if not snapshot.entries:
        issues.append("snapshot contains no public surface entries")
    seen: set[tuple[str, str]] = set()
    for entry in snapshot.entries:
        if entry.kind not in {"cli", "config", "export", "rest", "schema"}:
            issues.append(f"unknown public surface kind: {entry.kind or '<empty>'}")
            continue
        if not entry.name or not entry.signature:
            issues.append(f"malformed public surface entry: {entry.kind}:{entry.name}")
            continue
        identity = (entry.kind, entry.name)
        if identity in seen:
            issues.append(f"duplicate public surface entry: {entry.kind}:{entry.name}")
        seen.add(identity)
        if entry.kind in {"export", "rest", "schema"}:
            try:
                json.loads(entry.signature)
            except json.JSONDecodeError:
                issues.append(f"legacy/incomplete structural signature: {entry.kind}:{entry.name}")
        if entry.kind == "export" and entry.meta.get("inspection") != "runtime-signature":
            issues.append(f"Python export inspection incomplete: {entry.name}")
        if entry.kind != "cli":
            continue
        if entry.meta.get("inspection") != "argparse+handler-ast":
            issues.append(f"CLI inspection incomplete: {entry.name}")
            continue
        try:
            contract = json.loads(entry.signature)
        except json.JSONDecodeError:
            issues.append(f"invalid CLI signature: {entry.name}")
            continue
        if not isinstance(contract, Mapping):
            issues.append(f"malformed CLI signature: {entry.name}")
            continue
        path = contract.get("path")
        if not isinstance(path, list) or (not path and contract.get("root") is not True):
            issues.append(f"CLI command path missing: {entry.name}")
        if not isinstance(contract.get("arguments"), list):
            issues.append(f"CLI arguments incomplete: {entry.name}")
        if not isinstance(contract.get("mutually_exclusive_groups"), list):
            issues.append(f"CLI mutually-exclusive groups incomplete: {entry.name}")
        subcommands = contract.get("subcommands")
        if not isinstance(subcommands, list):
            issues.append(f"CLI subcommands incomplete: {entry.name}")
            subcommands = []
        handler = contract.get("handler_contract") if isinstance(contract, dict) else None
        if handler is None and not subcommands:
            issues.append(f"CLI leaf command has no inspectable handler: {entry.name}")
            continue
        if isinstance(handler, Mapping) and handler.get("output_complete") is not True:
            issues.append(f"CLI output inspection incomplete: {entry.name}")
    return issues


def _run_git(repo_root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        check=False,
        env=_inspection_environment(),
    )


def _resolve_base_ref(repo_root: Path, requested: str | None) -> str | None:
    candidates: list[str] = []
    if requested:
        candidates.append(requested)
    else:
        symbolic = _run_git(
            repo_root,
            ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        )
        if symbolic.returncode == 0:
            value = symbolic.stdout.decode("utf-8", errors="replace").strip()
            if value:
                candidates.append(value)
        candidates.extend(DEFAULT_BASE_REFS)

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        exists = _run_git(
            repo_root,
            ["rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"],
        )
        if exists.returncode == 0:
            return candidate
    return None


def _is_git_worktree(repo_root: Path) -> bool:
    proc = _run_git(repo_root, ["rev-parse", "--is-inside-work-tree"])
    return proc.returncode == 0 and proc.stdout.decode(
        "utf-8", errors="replace"
    ).strip() == "true"


def _repo_relative_path(repo_root: Path, path: Path) -> str | None:
    resolved = path if path.is_absolute() else repo_root / path
    try:
        return resolved.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return None


def _load_committed_snapshot(
    repo_root: Path,
    *,
    base_ref: str,
    baseline_path: Path,
) -> ApiSnapshot | None:
    relative = _repo_relative_path(repo_root, baseline_path)
    if relative is None:
        return None
    proc = _run_git(repo_root, ["show", f"{base_ref}:{relative}"])
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return _snapshot_from_data(data)


def _extract_archive_members(tar: tarfile.TarFile, temp_root: Path) -> str | None:
    """Extract with the ``data`` filter, or hand-validate members where the
    interpreter predates ``filter=`` (< 3.10.12 / 3.11.4).

    Never extract unfiltered: a member the ``data`` filter would reject fails
    closed with a bounded reason instead of being materialized.
    """
    try:
        tar.extractall(temp_root, filter="data")
        return None
    except TypeError:
        pass  # filter= unavailable on this interpreter; validate by hand below.
    resolved_root = temp_root.resolve()
    members = tar.getmembers()
    for member in members:
        name = member.name
        if not (member.isreg() or member.isdir()):
            return _redact_message(
                f"api_snapshot_tar_member_unsafe: non-regular member {name!r}"
            )
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts:
            return _redact_message(
                f"api_snapshot_tar_member_unsafe: path escape in {name!r}"
            )
        destination = (temp_root / name).resolve()
        if destination != resolved_root and resolved_root not in destination.parents:
            return _redact_message(
                f"api_snapshot_tar_member_unsafe: destination escape in {name!r}"
            )
    tar.extractall(temp_root, members=members)
    return None


def _capture_snapshot_from_ref(
    repo_root: Path,
    *,
    base_ref: str,
) -> tuple[ApiSnapshot | None, str | None]:
    """Capture ``base_ref`` from a temporary git archive without checkout mutation."""
    archive = _run_git(repo_root, ["archive", "--format=tar", base_ref])
    if archive.returncode != 0:
        detail = _redact_message(
            archive.stderr.decode("utf-8", errors="replace")
        ).strip()
        return None, detail or f"git archive failed for {base_ref}"
    try:
        with tempfile.TemporaryDirectory(prefix="elves-api-baseline-") as raw:
            temp_root = Path(raw)
            with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tar:
                extract_error = _extract_archive_members(tar, temp_root)
                if extract_error is not None:
                    return None, extract_error
            return capture_snapshot(temp_root), None
    except (OSError, tarfile.TarError) as exc:
        return None, _redact_message(f"could not inspect {base_ref} archive: {exc}")


def _json_contract(signature: str) -> dict[str, Any] | None:
    try:
        value = json.loads(signature)
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _stable_items(values: Any) -> set[str] | None:
    if values is None:
        return None
    if not isinstance(values, list):
        return set()
    return {
        json.dumps(value, sort_keys=True, separators=(",", ":"))
        for value in values
    }


def _cli_argument_label(argument: Mapping[str, Any]) -> str:
    flags = argument.get("flags")
    if isinstance(flags, list) and flags:
        return "/".join(str(flag) for flag in flags)
    return str(argument.get("dest") or "<positional>")


def _match_cli_argument(
    baseline: Mapping[str, Any],
    current: Sequence[Mapping[str, Any]],
    used: set[int],
) -> tuple[int, Mapping[str, Any]] | None:
    """Match an argparse action by stable public identity.

    ``dest`` is preferred because it survives adding an option alias.  Exact or
    overlapping option spellings are the fallback because a handler may rename
    its private namespace destination while preserving the public flags.
    """
    baseline_dest = baseline.get("dest")
    baseline_flags = {
        str(flag) for flag in (baseline.get("flags") or []) if isinstance(flag, str)
    }
    if baseline_flags:
        for index, candidate in enumerate(current):
            current_flags = {
                str(flag)
                for flag in (candidate.get("flags") or [])
                if isinstance(flag, str)
            }
            if (
                index not in used
                and candidate.get("dest") == baseline_dest
                and baseline_flags & current_flags
            ):
                return index, candidate
    for index, candidate in enumerate(current):
        if index not in used and candidate.get("dest") == baseline_dest:
            return index, candidate
    if baseline_flags:
        for index, candidate in enumerate(current):
            current_flags = {
                str(flag)
                for flag in (candidate.get("flags") or [])
                if isinstance(flag, str)
            }
            if index not in used and baseline_flags & current_flags:
                return index, candidate
    return None


def _cli_break_reasons(baseline_signature: str, current_signature: str) -> list[str]:
    """Return backward-incompatible CLI contract changes.

    Help prose, handler function names, print-call multiplicity, new optional
    arguments, new option aliases, new choices, new JSON keys, and new
    subcommands are compatible.  Existing invocation syntax and behavior stay
    fail-closed: removed flags/commands/keys, newly required inputs, changed
    defaults/consts/types/arity, narrowed choices, newly exclusive or required
    groups, and exit-code contract changes are breaking.
    """
    if baseline_signature == current_signature:
        return []
    baseline = _json_contract(baseline_signature)
    current = _json_contract(current_signature)
    required_shape = {
        "arguments",
        "mutually_exclusive_groups",
        "path",
        "subcommands",
    }
    if (
        baseline is None
        or current is None
        or not required_shape.issubset(baseline)
        or not required_shape.issubset(current)
    ):
        return ["CLI inspection changed or is incomplete"]

    reasons: list[str] = []
    baseline_path = baseline.get("path")
    current_path = current.get("path")
    if baseline_path != current_path:
        reasons.append(f"command path changed: {baseline_path!r} -> {current_path!r}")

    baseline_subcommands = {
        str(item) for item in (baseline.get("subcommands") or [])
    }
    current_subcommands = {str(item) for item in (current.get("subcommands") or [])}
    missing_subcommands = sorted(baseline_subcommands - current_subcommands)
    if missing_subcommands:
        reasons.append("subcommands removed: " + ", ".join(missing_subcommands))

    baseline_arguments = [
        item
        for item in (baseline.get("arguments") or [])
        if isinstance(item, Mapping)
    ]
    current_arguments = [
        item
        for item in (current.get("arguments") or [])
        if isinstance(item, Mapping)
    ]
    # Malformed structured contracts must not silently look like an empty CLI.
    if len(baseline_arguments) != len(baseline.get("arguments") or []):
        reasons.append("baseline argument contract is malformed")
    if len(current_arguments) != len(current.get("arguments") or []):
        reasons.append("current argument contract is malformed")

    used_current: set[int] = set()
    current_to_baseline: dict[int, int] = {}
    for baseline_index, baseline_argument in enumerate(baseline_arguments):
        label = _cli_argument_label(baseline_argument)
        matched = _match_cli_argument(
            baseline_argument,
            current_arguments,
            used_current,
        )
        if matched is None:
            reasons.append(f"argument removed or renamed: {label}")
            continue
        current_index, current_argument = matched
        used_current.add(current_index)
        current_to_baseline[current_index] = baseline_index

        baseline_flags = {
            str(flag) for flag in (baseline_argument.get("flags") or [])
        }
        current_flags = {
            str(flag) for flag in (current_argument.get("flags") or [])
        }
        missing_flags = sorted(baseline_flags - current_flags)
        if missing_flags:
            reasons.append(f"{label} removed flag(s): {', '.join(missing_flags)}")

        for field_name in ("action", "const", "default", "nargs", "type"):
            if baseline_argument.get(field_name) != current_argument.get(field_name):
                reasons.append(
                    f"{label} changed {field_name}: "
                    f"{baseline_argument.get(field_name)!r} -> "
                    f"{current_argument.get(field_name)!r}"
                )
        if not bool(baseline_argument.get("required")) and bool(
            current_argument.get("required")
        ):
            reasons.append(f"{label} became required")

        baseline_choices = _stable_items(baseline_argument.get("choices"))
        current_choices = _stable_items(current_argument.get("choices"))
        if baseline_choices is None:
            if current_choices is not None:
                reasons.append(f"{label} now restricts accepted choices")
        elif current_choices is not None:
            removed_choices = baseline_choices - current_choices
            if removed_choices:
                reasons.append(f"{label} removed accepted choice(s)")

    # A newly required action changes every existing invocation of the command.
    for index, current_argument in enumerate(current_arguments):
        if index in used_current:
            continue
        if bool(current_argument.get("required")):
            reasons.append(
                f"new required argument: {_cli_argument_label(current_argument)}"
            )

    def group_member_index(
        member: Any,
        arguments: Sequence[Mapping[str, Any]],
    ) -> int | None:
        if not isinstance(member, Mapping):
            return None
        dest = member.get("dest")
        flags = {
            str(flag) for flag in (member.get("flags") or []) if isinstance(flag, str)
        }
        exact = [
            index
            for index, argument in enumerate(arguments)
            if argument.get("dest") == dest
            and {
                str(flag)
                for flag in (argument.get("flags") or [])
                if isinstance(flag, str)
            }
            == flags
        ]
        if len(exact) == 1:
            return exact[0]
        overlap = [
            index
            for index, argument in enumerate(arguments)
            if argument.get("dest") == dest
            and flags
            & {
                str(flag)
                for flag in (argument.get("flags") or [])
                if isinstance(flag, str)
            }
        ]
        if len(overlap) == 1:
            return overlap[0]
        same_dest = [
            index
            for index, argument in enumerate(arguments)
            if argument.get("dest") == dest
        ]
        return same_dest[0] if len(same_dest) == 1 else None

    def group_sets(
        contract: Mapping[str, Any],
        arguments: Sequence[Mapping[str, Any]],
        *,
        current_contract: bool,
    ) -> tuple[list[tuple[set[str], bool]], bool]:
        groups: list[tuple[set[str], bool]] = []
        malformed = False
        raw_groups = contract.get("mutually_exclusive_groups")
        if not isinstance(raw_groups, list):
            return groups, True
        for item in raw_groups:
            if not isinstance(item, Mapping) or not isinstance(item.get("members"), list):
                malformed = True
                continue
            members = item.get("members") or []
            tokens: set[str] = set()
            for member in members:
                index = group_member_index(member, arguments)
                if index is None:
                    malformed = True
                    continue
                if current_contract:
                    baseline_index = current_to_baseline.get(index)
                    token = (
                        f"baseline:{baseline_index}"
                        if baseline_index is not None
                        else "new:"
                        + json.dumps(
                            arguments[index], sort_keys=True, separators=(",", ":")
                        )
                    )
                else:
                    token = f"baseline:{index}"
                tokens.add(token)
            if not members or len(tokens) != len(members):
                malformed = True
                continue
            groups.append((tokens, bool(item.get("required"))))
        return groups, malformed

    baseline_groups, baseline_groups_malformed = group_sets(
        baseline,
        baseline_arguments,
        current_contract=False,
    )
    current_groups, current_groups_malformed = group_sets(
        current,
        current_arguments,
        current_contract=True,
    )
    if baseline_groups_malformed:
        reasons.append("baseline mutually-exclusive group contract is malformed")
    if current_groups_malformed:
        reasons.append("current mutually-exclusive group contract is malformed")
    baseline_pairs = {
        tuple(sorted((left, right)))
        for members, _required in baseline_groups
        for left in members
        for right in members
        if left < right
    }
    current_pairs = {
        tuple(sorted((left, right)))
        for members, _required in current_groups
        for left in members
        for right in members
        if left < right
    }
    new_pairs = sorted(current_pairs - baseline_pairs)
    if new_pairs:
        reasons.append(
            "arguments became mutually exclusive: "
            + ", ".join(f"{left}/{right}" for left, right in new_pairs)
        )
    baseline_required_groups = [
        members for members, required in baseline_groups if required
    ]
    for current_members, current_required in current_groups:
        if not current_required:
            continue
        if not any(
            baseline_members <= current_members
            for baseline_members in baseline_required_groups
        ):
            reasons.append(
                "mutually-exclusive group became required: "
                + ", ".join(sorted(current_members))
            )

    baseline_handler = baseline.get("handler_contract")
    current_handler = current.get("handler_contract")
    if isinstance(baseline_handler, Mapping):
        if not isinstance(current_handler, Mapping):
            reasons.append("handler output contract was removed")
        else:
            baseline_keys = {
                str(key) for key in (baseline_handler.get("output_keys") or [])
            }
            current_keys = {
                str(key) for key in (current_handler.get("output_keys") or [])
            }
            removed_keys = sorted(baseline_keys - current_keys)
            if removed_keys:
                reasons.append("JSON output keys removed: " + ", ".join(removed_keys))

            def json_variants(handler: Mapping[str, Any]) -> tuple[list[set[str]], bool]:
                raw_variants = handler.get("output_variants")
                if not isinstance(raw_variants, list):
                    return [], False
                variants: list[set[str]] = []
                for variant in raw_variants:
                    if not isinstance(variant, Mapping) or variant.get("json") is not True:
                        continue
                    keys = variant.get("keys")
                    if not isinstance(keys, list) or not all(
                        isinstance(key, str) for key in keys
                    ):
                        return variants, False
                    variants.append(set(keys))
                unique = {
                    frozenset(keys)
                    for keys in variants
                }
                return [set(keys) for keys in unique], True

            baseline_variants, baseline_variants_valid = json_variants(baseline_handler)
            current_variants, current_variants_valid = json_variants(current_handler)
            if not baseline_variants_valid or not current_variants_valid:
                reasons.append("JSON output variant inspection is incomplete")
            else:
                ordered_baseline = sorted(
                    baseline_variants,
                    key=lambda keys: (-len(keys), sorted(keys)),
                )

                def variants_preserved(index: int, used: set[int]) -> bool:
                    if index >= len(ordered_baseline):
                        return True
                    expected = ordered_baseline[index]
                    for candidate_index, candidate in enumerate(current_variants):
                        if candidate_index in used or not expected <= candidate:
                            continue
                        used.add(candidate_index)
                        if variants_preserved(index + 1, used):
                            return True
                        used.remove(candidate_index)
                    return False

                if not variants_preserved(0, set()):
                    reasons.append("JSON output variant lost keys or emission")

            if "exit_codes" in baseline_handler and "exit_codes" in current_handler:
                baseline_exit = (
                    list(baseline_handler.get("exit_codes") or []),
                    bool(baseline_handler.get("dynamic_exit")),
                    list(baseline_handler.get("dynamic_exit_expressions") or []),
                )
                current_exit = (
                    list(current_handler.get("exit_codes") or []),
                    bool(current_handler.get("dynamic_exit")),
                    list(current_handler.get("dynamic_exit_expressions") or []),
                )
            else:
                # Older persisted snapshots did not have normalized exit codes.
                # Keep comparison fail-closed rather than guessing equivalence.
                baseline_exit = list(baseline_handler.get("exit_expressions") or [])
                current_exit = list(current_handler.get("exit_expressions") or [])
            if baseline_exit != current_exit:
                reasons.append("process exit contract changed")

    return reasons


def _json_schema_break_reasons(
    baseline_signature: str,
    current_signature: str,
) -> list[str]:
    """Return backward-incompatible JSON Schema contract changes.

    The snapshot stores one structural signature for a standalone JSON Schema,
    so a newly documented optional property changes that signature even though
    existing producers and consumers remain valid.  Treat only additive,
    non-required properties as compatible; every other structural change stays
    fail-closed.  The comparison is recursive so optional fields added to a
    nested object receive the same treatment without weakening existing field
    definitions.
    """
    if baseline_signature == current_signature:
        return []
    baseline = _json_contract(baseline_signature)
    current = _json_contract(current_signature)
    if baseline is None or current is None:
        return ["JSON Schema inspection changed or is incomplete"]

    reasons: list[str] = []

    def compare(baseline_value: Any, current_value: Any, *, path: str) -> None:
        if isinstance(baseline_value, Mapping):
            if not isinstance(current_value, Mapping):
                reasons.append(f"{path} changed object shape")
                return
            baseline_keys = {str(key) for key in baseline_value}
            current_keys = {str(key) for key in current_value}
            for missing in sorted(baseline_keys - current_keys):
                reasons.append(f"{path}.{missing} was removed")
            for added in sorted(current_keys - baseline_keys):
                reasons.append(f"{path}.{added} keyword was added")

            baseline_required = baseline_value.get("required")
            current_required = current_value.get("required")
            if baseline_required != current_required:
                reasons.append(f"{path}.required changed")

            for key in sorted(baseline_keys & current_keys):
                if key in {"properties", "required"}:
                    continue
                compare(
                    baseline_value[key],
                    current_value[key],
                    path=f"{path}.{key}",
                )

            baseline_properties = baseline_value.get("properties")
            current_properties = current_value.get("properties")
            if baseline_properties is None and current_properties is None:
                return
            if not isinstance(baseline_properties, Mapping) or not isinstance(
                current_properties, Mapping
            ):
                reasons.append(f"{path}.properties changed object shape")
                return
            baseline_property_names = {str(key) for key in baseline_properties}
            current_property_names = {str(key) for key in current_properties}
            for missing in sorted(
                baseline_property_names - current_property_names
            ):
                reasons.append(f"{path}.properties.{missing} was removed")
            required_names = {
                str(item)
                for item in (current_required or [])
                if isinstance(item, str)
            }
            for added in sorted(
                current_property_names - baseline_property_names
            ):
                if added in required_names:
                    reasons.append(
                        f"{path}.properties.{added} was added as required"
                    )
            for name in sorted(
                baseline_property_names & current_property_names
            ):
                compare(
                    baseline_properties[name],
                    current_properties[name],
                    path=f"{path}.properties.{name}",
                )
            return
        if isinstance(baseline_value, list):
            if baseline_value != current_value:
                reasons.append(f"{path} changed")
            return
        if baseline_value != current_value:
            reasons.append(f"{path} changed")

    compare(baseline, current, path="schema")
    return list(dict.fromkeys(reasons))


def diff_snapshots(
    baseline: ApiSnapshot,
    current: ApiSnapshot,
) -> dict[str, Any]:
    base_map = {(e.kind, e.name): e.signature for e in baseline.entries}
    cur_map = {(e.kind, e.name): e.signature for e in current.entries}
    added = sorted(k for k in cur_map if k not in base_map)
    removed = sorted(k for k in base_map if k not in cur_map)
    changed = sorted(k for k in base_map if k in cur_map and base_map[k] != cur_map[k])
    breaking_changes: list[tuple[str, str]] = []
    compatible_changes: list[tuple[str, str]] = []
    change_reasons: dict[str, list[str]] = {}
    for key in changed:
        if key[0] == "cli":
            reasons = _cli_break_reasons(base_map[key], cur_map[key])
        elif key[0] == "schema":
            reasons = _json_schema_break_reasons(base_map[key], cur_map[key])
        else:
            # Non-CLI entries retain strict legacy behavior.  Their collectors
            # already encode compatible additions as distinct entries.
            reasons = ["public signature changed"]
        rendered = f"{key[0]}:{key[1]}"
        if reasons:
            breaking_changes.append(key)
            change_reasons[rendered] = reasons
        else:
            compatible_changes.append(key)
    internal_only = baseline.digest() == current.digest()
    return {
        "added": [f"{k[0]}:{k[1]}" for k in added],
        "removed": [f"{k[0]}:{k[1]}" for k in removed],
        "changed": [f"{k[0]}:{k[1]}" for k in changed],
        "breaking": [f"{k[0]}:{k[1]}" for k in removed + breaking_changes],
        "compatible_additions": [f"{k[0]}:{k[1]}" for k in added],
        "compatible_changes": [f"{k[0]}:{k[1]}" for k in compatible_changes],
        "change_reasons": change_reasons,
        "identical": internal_only and not added and not removed and not changed,
    }


def _compatibility_gate_unredacted(
    repo_root: Path,
    *,
    baseline_path: Path | None = None,
    current_path: Path | None = None,
    required: bool = False,
    approved_breaks: Sequence[str] | None = None,
    base_ref: str | None = None,
) -> dict[str, Any]:
    """Diff public surface. Internal-only changes pass; unapproved breaks fail when required."""
    root = Path(repo_root).resolve()
    base_p = root / (baseline_path or DEFAULT_BASELINE)
    cur_p = root / (current_path or DEFAULT_CURRENT)
    current = capture_snapshot(root)
    write_snapshot(cur_p, current)
    if required and current.status != "captured":
        return {
            "ok": False,
            "status": "required_failed",
            "action": "current_inspection_incomplete",
            "required": True,
            "reason": current.reason or "current public surface inspection is incomplete",
            "baseline_source": "not_inspected",
            "breaking": [],
        }
    baseline = load_snapshot(base_p)
    baseline_source = f"file:{base_p}"
    # Candidate-local runtime snapshots are useful only when no repository base
    # exists.  Once Git provides a default/base ref, both advisory and required
    # checks compare with that ref so an older inspector cannot poison later
    # verification with a stale local contract shape.  An explicitly supplied
    # advisory baseline_path remains authoritative for callers that deliberately
    # manage their own snapshot file.
    resolved_ref = _resolve_base_ref(root, base_ref)
    if (
        not required
        and baseline_path is None
        and resolved_ref is None
        and _is_git_worktree(root)
    ):
        # A candidate-local file cannot become its own compatibility baseline in
        # a repository.  Report advisory degradation and leave no trusted-looking
        # baseline artifact behind.
        return {
            "ok": True,
            "status": "degraded",
            "capture_status": current.status,
            "action": "advisory_baseline_unresolved",
            "required": False,
            "reason": "no resolvable repository base ref; compatibility was not compared",
            "baseline_source": "unresolved",
            "breaking": [],
        }
    prefer_ref_baseline = required or (
        baseline_path is None and resolved_ref is not None
    )
    if prefer_ref_baseline:
        if resolved_ref is None:
            return {
                "ok": False,
                "status": "required_failed",
                "action": "required_baseline_missing",
                "required": True,
                "reason": (
                    "required public-API baseline must come from a resolvable "
                    "default/base ref; candidate-local baseline artifacts are not trusted"
                ),
                "baseline_source": "unresolved",
                "breaking": [],
            }
        # Always apply the current inspector to the historical source tree.
        # A committed snapshot can be internally well-formed while omitting an
        # entire surface family, so it cannot prove coverage for a strict gate.
        ref_baseline, capture_error = _capture_snapshot_from_ref(
            root,
            base_ref=resolved_ref,
        )
        baseline_source = f"captured:{resolved_ref}"
        if ref_baseline is not None and ref_baseline.status == "captured":
            baseline = ref_baseline
        elif required:
            reason = capture_error or (
                ref_baseline.reason
                if ref_baseline is not None
                else "baseline capture failed"
            )
            return {
                "ok": False,
                "status": "required_failed",
                "action": "required_baseline_missing",
                "required": True,
                "reason": reason,
                "baseline_source": baseline_source,
                "breaking": [],
            }
        else:
            reason = capture_error or (
                ref_baseline.reason
                if ref_baseline is not None
                else "repository baseline capture failed"
            )
            return {
                "ok": True,
                "status": "degraded",
                "capture_status": current.status,
                "action": "advisory_baseline_incomplete",
                "required": False,
                "reason": reason,
                "baseline_source": baseline_source,
                "breaking": [],
            }
    elif baseline is None:
        # Optional first capture may seed a local run artifact. Required mode
        # never enters this branch and therefore never baselines the candidate.
        write_snapshot(base_p, current)
        return {
            "ok": True,
            "status": current.status,
            "action": "baseline_created",
            "required": False,
            "breaking": [],
            "diff": {"identical": True, "added": [], "removed": [], "changed": []},
        }

    if baseline is None:  # Defensive narrowing for type checkers and future edits.
        return {
            "ok": False,
            "status": "required_failed",
            "action": "required_baseline_missing",
            "required": required,
            "reason": "baseline could not be loaded",
            "breaking": [],
        }
    if required and baseline.status != "captured":
        return {
            "ok": False,
            "status": "required_failed",
            "action": "required_baseline_unavailable",
            "required": True,
            "reason": baseline.reason or "required baseline has no captured public surface",
            "baseline_source": baseline_source,
            "breaking": [],
        }
    if baseline.status == "unavailable" and current.status == "unavailable":
        return {
            "ok": not required,
            "status": "unavailable",
            "action": "unavailable",
            "required": required,
            "reason": current.reason or baseline.reason,
            "breaking": [],
        }
    diff = diff_snapshots(baseline, current)
    approved = set(approved_breaks or [])
    unapproved = [item for item in diff["breaking"] if item not in approved]
    ok = not unapproved
    if not required and current.status in {"unavailable", "degraded"}:
        ok = True
    return {
        "ok": ok,
        "status": current.status,
        "action": "diffed_degraded" if current.status == "degraded" else "diffed",
        "required": required,
        "breaking": unapproved,
        "diff": diff,
        "baseline_source": baseline_source,
        "baseline_digest": baseline.digest(),
        "current_digest": current.digest(),
    }


def compatibility_gate(
    repo_root: Path,
    *,
    baseline_path: Path | None = None,
    current_path: Path | None = None,
    required: bool = False,
    approved_breaks: Sequence[str] | None = None,
    base_ref: str | None = None,
) -> dict[str, Any]:
    """Diff public surface and redact every externally surfaced diagnostic."""
    result = _compatibility_gate_unredacted(
        repo_root,
        baseline_path=baseline_path,
        current_path=current_path,
        required=required,
        approved_breaks=approved_breaks,
        base_ref=base_ref,
    )
    redacted = _redact_payload(result)
    return dict(redacted) if isinstance(redacted, Mapping) else result
