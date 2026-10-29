"""AST-whitelisted expressions. Never eval/exec, attributes or subscripting."""
import ast
import operator
import re
import pandas as pd
from .money import decimal

OPS = {"eq": operator.eq, "ne": operator.ne, "gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le}

def filter_mask(df: pd.DataFrame, filters: list[dict]) -> pd.Series:
    """AND a list of whitelisted declarative column conditions."""
    mask = pd.Series(True, index=df.index)
    for item in filters:
        col, op, value = item["col"], item["op"], item.get("val")
        if col not in df:
            raise ValueError(f"Column '{col}' not found. Check mappings or remap with the agent.")
        series = df[col]
        if op in OPS:
            if isinstance(value, (int, float)):
                series = pd.to_numeric(series, errors="coerce")
            elif value is not None:
                series = series.astype(str)
                value = str(value)
            result = OPS[op](series, value)
        elif op in ("in", "not_in"):
            result = series.isin(value) | series.astype(str).isin([str(v) for v in value])
            if op == "not_in":
                result = ~result
        elif op in ("startswith", "contains", "regex"):
            series = series.fillna("").astype(str)
            if op == "startswith":
                result = series.str.startswith(str(value))
            else:
                if op == "regex" and len(str(value)) > 500:
                    raise ValueError("Regex patterns must be shorter than 500 characters.")
                result = series.str.contains(str(value), regex=op == "regex", na=False)
        elif op == "isnull":
            result = series.isna()
        elif op == "notnull":
            result = series.notna()
        else:
            raise ValueError(f"Unsupported filter '{op}'. Choose a supported operator.")
        mask &= result.fillna(False)
    return mask

def evaluate(expression: str, df: pd.DataFrame) -> object:
    """Vectorized safe evaluation of the documented tiny expression grammar."""
    if len(expression) > 4000:
        raise ValueError("Expression is too long.")
    try:
        root = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError("Invalid rule expression. Check its syntax.") from exc
    if len(list(ast.walk(root))) > 500:
        raise ValueError("Expression is too complex.")
    def visit(node: ast.AST) -> object:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float, bool, type(None))):
            return decimal(node.value) if isinstance(node.value, (int, float)) and not isinstance(node.value, bool) else node.value
        if isinstance(node, ast.Name) and node.id in df.columns:
            series = df[node.id]
            if pd.api.types.is_bool_dtype(series):
                return series
            numeric = pd.to_numeric(series, errors="coerce")
            if series.notna().sum() == numeric.notna().sum():
                return series.map(lambda value: None if pd.isna(value) else decimal(value))
            return series
        if isinstance(node, (ast.List, ast.Tuple)):
            return [visit(v) for v in node.elts]
        if isinstance(node, ast.BoolOp):
            values = [visit(v) for v in node.values]
            result = values[0]
            for v in values[1:]:
                result = result & v if isinstance(node.op, ast.And) else result | v
            return result
        if isinstance(node, ast.UnaryOp):
            value = visit(node.operand)
            if isinstance(node.op, ast.Not):
                return ~value if isinstance(value, pd.Series) else not value
            if isinstance(node.op, ast.USub):
                return -value
            if isinstance(node.op, ast.UAdd):
                return value
        if isinstance(node, ast.BinOp):
            operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
            if type(node.op) in operations:
                return operations[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.Compare):
            left, result = visit(node.left), True
            for op, right_node in zip(node.ops, node.comparators):
                right = visit(right_node)
                operations = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le}
                if isinstance(op, (ast.In, ast.NotIn)):
                    value = left.isin(right) if isinstance(left, pd.Series) else left in right
                    if isinstance(op, ast.NotIn):
                        value = ~value if isinstance(value, pd.Series) else not value
                elif type(op) in operations:
                    value = operations[type(op)](left, right)
                else:
                    raise ValueError("That comparison is not allowed.")
                result = result & value
                left = right
            return result
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
            args = [visit(v) for v in node.args]
            if node.func.id == "abs" and len(args) == 1:
                return abs(args[0])
            if node.func.id == "isnull" and len(args) == 1:
                return pd.isna(args[0])
            if node.func.id in ("startswith", "contains") and len(args) == 2:
                series = args[0].fillna("").astype(str)
                return series.str.startswith(str(args[1])) if node.func.id == "startswith" else series.str.contains(str(args[1]), regex=False)
        raise ValueError("Unsafe or unknown expression. Only columns, arithmetic, comparisons, and approved functions are allowed.")
    return visit(root)
