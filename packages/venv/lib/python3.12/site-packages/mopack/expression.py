import operator
import pyparsing as pp
from functools import reduce
from pyparsing import ParseBaseException, ParseException

pp.ParserElement.enable_packrat(512)

__all__ = ['evaluate', 'evaluate_token', 'parse', 'ParseBaseException',
           'ParseException', 'SemanticException', 'Token']


class SemanticException(pp.ParseBaseException):
    pass


class Token:
    pass


class Literal(Token):
    def __init__(self, value):
        self.value = value

    def __call__(self, symbols):
        return self.value

    def __repr__(self):
        return '<Literal({!r})>'.format(self.value)


class ArrayLiteral(Literal):
    def __call__(self, symbols):
        return [i(symbols) for i in self.value]

    def __repr__(self):
        return '<ArrayLiteral({!r})>'.format(self.value)


class Symbol(Token):
    def __init__(self, pstr, loc, symbol):
        self._pstr = pstr
        self.loc = loc
        self.symbol = symbol

    def __call__(self, symbols):
        try:
            return symbols[self.symbol]
        except KeyError:
            msg = 'undefined symbol {!r}'.format(self.symbol)
            raise SemanticException(self._pstr, self.loc, msg)

    def __repr__(self):
        return '<Symbol({})>'.format(self.symbol)


class UnaryOp(Token):
    _simple_ops = {
        '!': operator.not_,
        '-': operator.neg,
    }

    def __init__(self, operator, operand):
        self.operator = operator
        self.operand = operand

    def __call__(self, symbols):
        return self._simple_ops[self.operator](self.operand(symbols))

    def __repr__(self):
        return '({}{})'.format(self.operator, self.operand)


class BinaryOp(Token):
    _simple_ops = {
        '*':  operator.mul,
        '/':  operator.truediv,
        '%':  operator.mod,
        '+':  operator.add,
        '-':  operator.sub,
        '<':  operator.lt,
        '<=': operator.le,
        '>':  operator.gt,
        '>=': operator.ge,
        '==': operator.eq,
        '!=': operator.ne,
    }

    def __init__(self, left, operator, right):
        self.operator = operator
        self.operands = [left, right]

    def __call__(self, symbols):
        if self.operator == '&&':
            return self.operands[0](symbols) and self.operands[1](symbols)
        if self.operator == '||':
            return self.operands[0](symbols) or self.operands[1](symbols)
        elif self.operator == '[]':
            left = self.operands[0](symbols)
            right = self.operands[1](symbols)
            if hasattr(left, 'get'):
                return left.get(right)
            return left[right]
        else:
            op = self._simple_ops[self.operator]
            return op(self.operands[0](symbols), self.operands[1](symbols))

    def __repr__(self):
        return '({} {} {})'.format(self.operands[0], self.operator,
                                   self.operands[1])


class TernaryOp(Token):
    def __init__(self, left, first_operator, middle, second_operator, right):
        self.operator = first_operator + second_operator
        self.operands = [left, middle, right]

    def __call__(self, symbols):
        if self.operator == '?:':
            return (self.operands[1](symbols) if self.operands[0](symbols)
                    else self.operands[2](symbols))
        assert False

    def __repr__(self):
        return '({} {} {}, {})'.format(self.operands[0], self.operator,
                                       *self.operands[1:])


class StringOp(Token):
    def __init__(self, ast):
        self.ast = ast

    def __call__(self, symbols):
        return reduce(operator.add, (
            evaluate_token(symbols, i) for i in self.ast
        ))


def left_assoc(operands, operator=None, index=None):
    if index is None:
        index = len(operands) - 1
    if index == 0:
        return operands[0]

    if operator is None:
        return BinaryOp(left_assoc(operands, operator, index - 2),
                        operands[index - 1], operands[index])
    return BinaryOp(left_assoc(operands, operator, index - 1),
                    operator, operands[index])


expr = pp.Forward()

integer_literal = pp.common.signed_integer.set_parse_action(
    lambda t: [Literal(int(t[0]))]
)

string_literal = (
    pp.QuotedString('"') | pp.QuotedString("'")
).set_parse_action(lambda t: [Literal(t[0])])

array_literal = (
    pp.Suppress('[') + pp.Optional(pp.delimited_list(expr)) + pp.Suppress(']')
).set_parse_action(lambda t: [ArrayLiteral(t.copy())])

true_literal = pp.Keyword('true').set_parse_action(lambda: [Literal(True)])
false_literal = pp.Keyword('false').set_parse_action(lambda: [Literal(False)])
bool_literal = true_literal | false_literal

null_literal = pp.Keyword('null').set_parse_action(lambda: [Literal(None)])

literal = (integer_literal | string_literal | array_literal | bool_literal |
           null_literal)

identifier = pp.Word(pp.alphas + '_', pp.alphanums + '_').set_parse_action(
    lambda s, loc, t: [Symbol(s, loc, t[0])]
)

pre_expr = literal | identifier | (pp.Suppress('(') + expr + pp.Suppress(')'))

index = (
    pre_expr + (pp.Suppress('[') + expr + pp.Suppress(']'))[1, ...]
).set_parse_action(lambda t: [left_assoc(t, '[]')])

expr_atom = literal | index | identifier
expr <<= pp.infix_notation(expr_atom, [
    (pp.one_of('! -'), 1, pp.opAssoc.RIGHT, lambda t: [UnaryOp(*t[0])]),
    (pp.one_of('* / %'), 2, pp.opAssoc.LEFT, lambda t: [left_assoc(t[0])]),
    (pp.one_of('+ -'), 2, pp.opAssoc.LEFT, lambda t: [left_assoc(t[0])]),
    (pp.one_of('> >= < <='), 2, pp.opAssoc.LEFT, lambda t: [left_assoc(t[0])]),
    (pp.one_of('== !='), 2, pp.opAssoc.LEFT, lambda t: [left_assoc(t[0])]),
    ('&&', 2, pp.opAssoc.LEFT, lambda t: [left_assoc(t[0])]),
    ('||', 2, pp.opAssoc.LEFT, lambda t: [left_assoc(t[0])]),
    (('?', ':'), 3, pp.opAssoc.RIGHT, lambda t: [TernaryOp(*t[0])]),
])

expr_holder = ('${{' + expr + '}}').set_parse_action(lambda t: t[1])
identifier_holder = ('$' + identifier).set_parse_action(lambda t: t[1])
escaped_dollar = pp.Literal('$$').set_parse_action(lambda: ['$'])
dollar_expr = escaped_dollar | identifier_holder | expr_holder

bare_string = (pp.SkipTo(pp.Literal('$') | pp.StringEnd()).leave_whitespace()
               .set_parse_action(lambda t: t if len(t[0]) else []))

if_expr = dollar_expr | expr
str_expr = bare_string + (dollar_expr + bare_string)[...]


def evaluate_token(symbols, tok):
    if isinstance(tok, Token):
        return tok(symbols)
    return tok


def parse(expression, if_context=False):
    if if_context:
        return if_expr.parse_string(expression, parseAll=True)[0]
    else:
        ast = str_expr.parse_string(expression, parseAll=True)
        if len(ast) == 0:
            return expression
        elif len(ast) == 1:
            return ast[0]
        else:
            return StringOp(ast)


def evaluate(symbols, expression, if_context=False):
    return evaluate_token(symbols, parse(expression, if_context))
