"""
A calculator for the agent.

Language models do arithmetic in their heads, and they are unreliable at
it -- confidently so, which is the dangerous part. A model that fetches
$9.2B revenue and then reports $41.5B has not lied to you, it has
miscalculated and stated the result with the same tone it uses for facts.
Handing the arithmetic to Python removes that failure mode entirely.

WHY NOT eval()

The obvious implementation is `eval(expression)`. Don't. eval executes
arbitrary Python, so any string that reaches it -- from a model, from a
user, from a web request -- can import modules, read files, or open a
socket. It doesn't matter that this app runs locally; the habit is the
problem.

Instead the expression is parsed into a syntax tree and walked, allowing
only the node types arithmetic needs. Anything else -- attribute access,
imports, subscripts, lambdas, function calls outside a small whitelist --
is rejected before evaluation, because it is structurally absent rather
than merely discouraged.
"""

from __future__ import annotations

import ast
import math
import operator

MAX_EXPRESSION_CHARS = 500
MAX_EXPONENT = 64          # 2 ** 1e9 would hang the process
MAX_ABS_RESULT = 1e30

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

_COMPARE = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne,
    ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge,
}

# Only functions that are pure, total, and cheap.
_FUNCTIONS = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "len": len, "sorted": sorted, "sqrt": math.sqrt, "floor": math.floor,
    "ceil": math.ceil,
}

_CONSTANTS = {"pi": math.pi, "e": math.e}


class CalculationError(ValueError):
    """Raised for anything the calculator refuses or cannot do."""


def _evaluate(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise CalculationError(f"only numbers are allowed, got {type(node.value).__name__}")

    if isinstance(node, (ast.List, ast.Tuple)):
        return [_evaluate(item) for item in node.elts]

    if isinstance(node, ast.BinOp):
        op = _BINARY.get(type(node.op))
        if op is None:
            raise CalculationError(f"operator {type(node.op).__name__} is not allowed")
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalculationError(f"exponent {right} is too large")
        try:
            return op(left, right)
        except ZeroDivisionError:
            raise CalculationError("division by zero") from None
        except Exception as exc:
            raise CalculationError(f"cannot evaluate: {exc}") from None

    if isinstance(node, ast.UnaryOp):
        op = _UNARY.get(type(node.op))
        if op is None:
            raise CalculationError(f"operator {type(node.op).__name__} is not allowed")
        return op(_evaluate(node.operand))

    if isinstance(node, ast.Compare):
        left = _evaluate(node.left)
        for op_node, right_node in zip(node.ops, node.comparators):
            op = _COMPARE.get(type(op_node))
            if op is None:
                raise CalculationError("comparison is not allowed")
            right = _evaluate(right_node)
            if not op(left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise CalculationError("only plain function names are allowed")
        func = _FUNCTIONS.get(node.func.id)
        if func is None:
            raise CalculationError(
                f"'{node.func.id}' is not available; allowed: {', '.join(sorted(_FUNCTIONS))}"
            )
        if node.keywords:
            raise CalculationError("keyword arguments are not allowed")
        args = [_evaluate(arg) for arg in node.args]
        try:
            return func(*args)
        except CalculationError:
            raise
        except Exception as exc:
            # sqrt(-1), min([]), round("x") -- a whitelisted function can
            # still fail. Convert at the boundary so callers only ever
            # have to handle one exception type.
            raise CalculationError(f"{node.func.id}: {exc}") from None

    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        raise CalculationError(f"unknown name '{node.id}'")

    raise CalculationError(f"{type(node).__name__} is not allowed in an expression")


def calculate(expression: str) -> dict:
    """Evaluate an arithmetic expression safely.

    Returns {"expression": ..., "result": ...}. Raises CalculationError,
    which the agent hands back to the model as data so it can explain the
    problem rather than crash.
    """
    if not isinstance(expression, str) or not expression.strip():
        raise CalculationError("expression is required")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise CalculationError(f"expression is too long (limit {MAX_EXPRESSION_CHARS} characters)")

    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise CalculationError(f"could not parse: {exc.msg}") from None

    result = _evaluate(tree.body)

    if isinstance(result, float):
        if math.isnan(result) or math.isinf(result):
            raise CalculationError("result is not a finite number")
        if abs(result) > MAX_ABS_RESULT:
            raise CalculationError("result is too large to be meaningful")
        result = round(result, 6)

    return {"expression": expression.strip(), "result": result}
