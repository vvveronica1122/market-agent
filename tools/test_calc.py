"""
Tests for the calculator -- mostly tests that it REFUSES things.

The arithmetic working is the easy half. The half worth testing is the
boundary: an expression evaluator that quietly accepts one attribute
access or one dunder is an arbitrary-code-execution hole with a friendly
name. Free, offline, instant.

    python3 tools/test_calc.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.calc import CalculationError, calculate


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    return condition


def refuses(expression) -> tuple[bool, str]:
    try:
        result = calculate(expression)
        return False, f"ACCEPTED and returned {result['result']!r}"
    except CalculationError as exc:
        return True, str(exc)
    except Exception as exc:  # a non-CalculationError escaping is itself a bug
        return False, f"raised {type(exc).__name__} instead of CalculationError: {exc}"


def main() -> int:
    failures = 0

    print("\nArithmetic")
    cases = [
        ("2 + 3 * 4", 14),
        ("(312.14 - 316.34) / 316.34 * 100", -1.327685),
        ("sum([9.2, 8.1, 7.4])", 24.7),
        ("round(41.5 / 3, 2)", 13.83),
        ("max([1, 9, 4]) - min([1, 9, 4])", 8),
        ("sqrt(144)", 12.0),
        ("abs(-7) ** 2", 49),
        ("len([1, 2, 3])", 3),
    ]
    for expression, expected in cases:
        try:
            got = calculate(expression)["result"]
            ok = abs(got - expected) < 1e-6
        except Exception as exc:
            got, ok = f"raised {exc}", False
        failures += not check(f"{expression} == {expected}", ok, f"got {got}")

    print("\nRefuses code execution (the point of the whole module)")
    dangerous = [
        '__import__("os").system("echo pwned")',
        'open("/etc/passwd").read()',
        "(1).__class__.__bases__",
        "().__class__.__mro__",
        "eval('1+1')",
        "exec('x=1')",
        "globals()",
        "[].append(1)",
        "lambda: 1",
        "[x for x in range(3)]",
        "print('hi')",
        "1 if True else 2",
        "a.b",
        "'string' + 'concat'",
        "{'a': 1}",
    ]
    for expression in dangerous:
        ok, detail = refuses(expression)
        failures += not check(f"refuses {expression[:38]}", ok, detail)

    print("\nRefuses resource exhaustion")
    for expression in ["2 ** 999999", "9 ** 9 ** 9", "x" * 600]:
        ok, detail = refuses(expression)
        failures += not check(f"refuses {expression[:30]}...", ok, detail)

    print("\nHandles bad input gracefully")
    for expression in ["", "   ", "2 +", "1 / 0", "sqrt(-1)"]:
        ok, detail = refuses(expression)
        failures += not check(f"refuses {expression!r}", ok, detail)

    failures += not check("non-string input is refused", refuses(None)[0])

    print(f"\n{'All checks passed.' if not failures else str(failures) + ' check(s) FAILED.'}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
