# Copyright 2014-2017 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from dataclasses import dataclass
import re
import codecs
import types
import typing as T
from .mesonlib import MesonException
from . import mlog

if T.TYPE_CHECKING:
    from .ast import AstVisitor

# This is the regex for the supported escape sequences of a regular string
# literal, like 'abc\x00'
ESCAPE_SEQUENCE_SINGLE_RE = re.compile(r'''
    ( \\U[A-Fa-f0-9]{8}   # 8-digit hex escapes
    | \\u[A-Fa-f0-9]{4}   # 4-digit hex escapes
    | \\x[A-Fa-f0-9]{2}   # 2-digit hex escapes
    | \\[0-7]{1,3}        # Octal escapes
    | \\N\{[^}]+\}        # Unicode characters by name
    | \\[\\'abfnrtv]      # Single-character escapes
    )''', re.UNICODE | re.VERBOSE)

class MesonUnicodeDecodeError(MesonException):
    def __init__(self, match: str) -> None:
        super().__init__(match)
        self.match = match

def decode_match(match: T.Match[str]) -> str:
    try:
        return codecs.decode(match.group(0).encode(), 'unicode_escape')
    except UnicodeDecodeError:
        raise MesonUnicodeDecodeError(match.group(0))

class ParseException(MesonException):
    def __init__(self, text: str, line: str, lineno: int, colno: int) -> None:
        # Format as error message, followed by the line with the error, followed by a caret to show the error column.
        super().__init__("{}\n{}\n{}".format(text, line, '{}^'.format(' ' * colno)))
        self.lineno = lineno
        self.colno = colno

class BlockParseException(MesonException):
    def __init__(
                self,
                text: str,
                line: str,
                lineno: int,
                colno: int,
                start_line: str,
                start_lineno: int,
                start_colno: int,
            ) -> None:
        # This can be formatted in two ways - one if the block start and end are on the same line, and a different way if they are on different lines.

        if lineno == start_lineno:
            # If block start and end are on the same line, it is formatted as:
            # Error message
            # Followed by the line with the error
            # Followed by a caret to show the block start
            # Followed by underscores
            # Followed by a caret to show the block end.
            super().__init__("{}\n{}\n{}".format(text, line, '{}^{}^'.format(' ' * start_colno, '_' * (colno - start_colno - 1))))
        else:
            # If block start and end are on different lines, it is formatted as:
            # Error message
            # Followed by the line with the error
            # Followed by a caret to show the error column.
            # Followed by a message saying where the block started.
            # Followed by the line of the block start.
            # Followed by a caret for the block start.
            super().__init__("%s\n%s\n%s\nFor a block that started at %d,%d\n%s\n%s" % (text, line, '%s^' % (' ' * colno), start_lineno, start_colno, start_line, "%s^" % (' ' * start_colno)))
        self.lineno = lineno
        self.colno = colno

TV_TokenTypes = T.TypeVar('TV_TokenTypes', int, str, bool)

@dataclass(eq=False)
class Token(T.Generic[TV_TokenTypes]):
    tid: str
    filename: str
    line_start: int
    lineno: int
    colno: int
    bytespan: T.Tuple[int, int]
    value: TV_TokenTypes

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.tid == other
        elif isinstance(other, Token):
            return self.tid == other.tid
        return NotImplemented

@dataclass(eq=False)
class Comment:
    line_start: int
    lineno: int
    colno: int
    bytespan: T.Tuple[int, int]
    text: str

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Comment):
            return self.line_start == other.line_start and self.colno == other.colno
        return False

class Lexer:
    def __init__(self, code: str):
        self.code = code
        self.keywords = {'true', 'false', 'if', 'else', 'elif',
                         'endif', 'and', 'or', 'not', 'foreach', 'endforeach',
                         'in', 'continue', 'break'}
        self.future_keywords = {'return'}
        self.comments = [] # type: T.List[Comment]
        self.token_specification = [
            # Need to be sorted longest to shortest.
            ('ignore', re.compile(r'[ \t]')),
            ('multiline_fstring', re.compile(r"f'''(.|\n)*?'''", re.M)),
            ('fstring', re.compile(r"f'([^'\\]|(\\.))*'")),
            ('id', re.compile('[_a-zA-Z][_0-9a-zA-Z]*')),
            ('number', re.compile(r'0[bB][01]+|0[oO][0-7]+|0[xX][0-9a-fA-F]+|0|[1-9]\d*')),
            ('eol_cont', re.compile(r'\\\n')),
            ('eol', re.compile(r'\n')),
            ('multiline_string', re.compile(r"'''(.|\n)*?'''", re.M)),
            ('comment', re.compile(r'#.*')),
            ('lparen', re.compile(r'\(')),
            ('rparen', re.compile(r'\)')),
            ('lbracket', re.compile(r'\[')),
            ('rbracket', re.compile(r'\]')),
            ('lcurl', re.compile(r'\{')),
            ('rcurl', re.compile(r'\}')),
            ('dblquote', re.compile(r'"')),
            ('string', re.compile(r"'([^'\\]|(\\.))*'")),
            ('comma', re.compile(r',')),
            ('plusassign', re.compile(r'\+=')),
            ('dot', re.compile(r'\.')),
            ('plus', re.compile(r'\+')),
            ('dash', re.compile(r'-')),
            ('star', re.compile(r'\*')),
            ('percent', re.compile(r'%')),
            ('fslash', re.compile(r'/')),
            ('colon', re.compile(r':')),
            ('equal', re.compile(r'==')),
            ('nequal', re.compile(r'!=')),
            ('assign', re.compile(r'=')),
            ('le', re.compile(r'<=')),
            ('lt', re.compile(r'<')),
            ('ge', re.compile(r'>=')),
            ('gt', re.compile(r'>')),
            ('questionmark', re.compile(r'\?')),
        ]

    def getline(self, line_start: int) -> str:
        return self.code[line_start:self.code.find('\n', line_start)]

    def lex(self, filename: str) -> T.Generator[Token, None, None]:
        line_start = 0
        lineno = 1
        loc = 0
        par_count = 0
        bracket_count = 0
        curl_count = 0
        col = 0
        while loc < len(self.code):
            matched = False
            value = None  # type: T.Union[str, bool, int]
            for (tid, reg) in self.token_specification:
                mo = reg.match(self.code, loc)
                if mo:
                    curline = lineno
                    curline_start = line_start
                    col = mo.start() - line_start
                    matched = True
                    span_start = loc
                    loc = mo.end()
                    span_end = loc
                    bytespan = (span_start, span_end)
                    match_text = mo.group()
                    if tid == 'ignore':
                        break
                    elif tid == 'lparen':
                        par_count += 1
                    elif tid == 'rparen':
                        par_count -= 1
                    elif tid == 'lbracket':
                        bracket_count += 1
                    elif tid == 'rbracket':
                        bracket_count -= 1
                    elif tid == 'lcurl':
                        curl_count += 1
                    elif tid == 'rcurl':
                        curl_count -= 1
                    elif tid == 'dblquote':
                        raise ParseException('Double quotes are not supported. Use single quotes.', self.getline(line_start), lineno, col)
                    elif tid in {'string', 'fstring'}:
                        # Handle here and not on the regexp to give a better error message.
                        if match_text.find("\n") != -1:
                            msg = ParseException("Newline character in a string detected, use ''' (three single quotes) "
                                                 "for multiline strings instead.\n"
                                                 "This will become a hard error in a future Meson release.",
                                                 self.getline(line_start), lineno, col)
                            mlog.warning(msg, location=BaseNode(lineno, col, filename))
                        value = match_text[2 if tid == 'fstring' else 1:-1]
                        try:
                            value = ESCAPE_SEQUENCE_SINGLE_RE.sub(decode_match, value)
                        except MesonUnicodeDecodeError as err:
                            raise MesonException(f"Failed to parse escape sequence: '{err.match}' in string:\n  {match_text}")
                    elif tid in {'multiline_string', 'multiline_fstring'}:
                        # For multiline strings, parse out the value and pass
                        # through the normal string logic.
                        # For multiline format strings, we have to emit a
                        # different AST node so we can add a feature check,
                        # but otherwise, it follows the normal fstring logic.
                        if tid == 'multiline_string':
                            value = match_text[3:-3]
                            tid = 'string'
                        else:
                            value = match_text[4:-3]
                        lines = match_text.split('\n')
                        if len(lines) > 1:
                            lineno += len(lines) - 1
                            line_start = mo.end() - len(lines[-1])
                    elif tid == 'number':
                        value = int(match_text, base=0)
                    elif tid == 'eol_cont':
                        lineno += 1
                        line_start = loc
                        break
                    elif tid == 'eol':
                        lineno += 1
                        line_start = loc
                        if par_count > 0 or bracket_count > 0 or curl_count > 0:
                            break
                    elif tid == 'comment':
                        self.comments.append(Comment(curline_start, curline, col, bytespan, match_text))
                        break
                    elif tid == 'id':
                        if match_text in self.keywords:
                            tid = match_text
                        else:
                            if match_text in self.future_keywords:
                                mlog.warning(f"Identifier '{match_text}' will become a reserved keyword in a future release. Please rename it.",
                                             location=types.SimpleNamespace(filename=filename, lineno=lineno))
                            value = match_text
                    yield Token(tid, filename, curline_start, curline, col, bytespan, value)
                    break
            if not matched:
                raise ParseException('lexer', self.getline(line_start), lineno, col)

@dataclass(eq=False)
class BaseNode:
    lineno: int
    colno: int
    filename: str
    end_lineno: T.Optional[int] = None
    end_colno: T.Optional[int] = None
    bytespan: T.Optional[T.Tuple[int, int]] = None
    pre_comments: T.Optional[T.List['Comment']] = None
    comments: T.Optional[T.List['Comment']] = None
    post_comments: T.Optional[T.List['Comment']] = None

    def __post_init__(self) -> None:
        if self.end_lineno is None:
            self.end_lineno = self.lineno
        if self.end_colno is None:
            self.end_colno = self.colno

        # Attributes for the visitors
        self.level = 0            # type: int
        self.ast_id = ''          # type: str
        self.condition_level = 0  # type: int
        self.pre_comments = []
        self.comments = []
        self.post_comments = []

    def accept(self, visitor: 'AstVisitor') -> None:
        fname = 'visit_{}'.format(type(self).__name__)
        if hasattr(visitor, fname):
            func = getattr(visitor, fname)
            if callable(func):
                func(self)

class ElementaryNode(T.Generic[TV_TokenTypes], BaseNode):
    def __init__(self, token: Token[TV_TokenTypes]):
        super().__init__(token.lineno, token.colno, token.filename)
        self.value = token.value        # type: TV_TokenTypes
        self.bytespan = token.bytespan  # type: T.Tuple[int, int]

class BooleanNode(ElementaryNode[bool]):
    def __init__(self, token: Token[bool]):
        super().__init__(token)
        assert isinstance(self.value, bool)

class IdNode(ElementaryNode[str]):
    def __init__(self, token: Token[str]):
        super().__init__(token)
        assert isinstance(self.value, str)

    def __str__(self) -> str:
        return "Id node: '%s' (%d, %d)." % (self.value, self.lineno, self.colno)

class NumberNode(ElementaryNode[int]):
    def __init__(self, token: Token[int]):
        super().__init__(token)
        assert isinstance(self.value, int)

class StringNode(ElementaryNode[str]):
    def __init__(self, token: Token[str]):
        super().__init__(token)
        assert isinstance(self.value, str)

    def __str__(self) -> str:
        return "String node: '%s' (%d, %d)." % (self.value, self.lineno, self.colno)

class FormatStringNode(ElementaryNode[str]):
    def __init__(self, token: Token[str]):
        super().__init__(token)
        assert isinstance(self.value, str)

    def __str__(self) -> str:
        return f"Format string node: '{self.value}' ({self.lineno}, {self.colno})."

class MultilineFormatStringNode(FormatStringNode):
    def __str__(self) -> str:
        return f"Multiline Format string node: '{self.value}' ({self.lineno}, {self.colno})."

class ContinueNode(ElementaryNode):
    pass

class BreakNode(ElementaryNode):
    pass

class ArgumentNode(BaseNode):
    def __init__(self, token: Token[TV_TokenTypes]):
        super().__init__(token.lineno, token.colno, token.filename)
        self.arguments = []  # type: T.List[BaseNode]
        self.commas = []     # type: T.List[Token[TV_TokenTypes]]
        self.kwargs = {}     # type: T.Dict[BaseNode, BaseNode]
        self.order_error = False

    def prepend(self, statement: BaseNode) -> None:
        if self.num_kwargs() > 0:
            self.order_error = True
        if not isinstance(statement, EmptyNode):
            self.arguments = [statement] + self.arguments

    def append(self, statement: BaseNode) -> None:
        if self.num_kwargs() > 0:
            self.order_error = True
        if not isinstance(statement, EmptyNode):
            self.arguments += [statement]

    def set_kwarg(self, name: IdNode, value: BaseNode) -> None:
        if any((isinstance(x, IdNode) and name.value == x.value) for x in self.kwargs):
            mlog.warning(f'Keyword argument "{name.value}" defined multiple times.', location=self)
            mlog.warning('This will be an error in future Meson releases.')
        self.kwargs[name] = value

    def set_kwarg_no_check(self, name: BaseNode, value: BaseNode) -> None:
        self.kwargs[name] = value

    def num_args(self) -> int:
        return len(self.arguments)

    def num_kwargs(self) -> int:
        return len(self.kwargs)

    def incorrect_order(self) -> bool:
        return self.order_error

    def __len__(self) -> int:
        return self.num_args() # Fixme

class ArrayNode(BaseNode):
    def __init__(self, args: ArgumentNode, lineno: int, colno: int, end_lineno: int, end_colno: int):
        super().__init__(lineno, colno, args.filename, end_lineno=end_lineno, end_colno=end_colno)
        self.args = args              # type: ArgumentNode

class DictNode(BaseNode):
    def __init__(self, args: ArgumentNode, lineno: int, colno: int, end_lineno: int, end_colno: int):
        super().__init__(lineno, colno, args.filename, end_lineno=end_lineno, end_colno=end_colno)
        self.args = args

class EmptyNode(BaseNode):
    def __init__(self, lineno: int, colno: int, filename: str):
        super().__init__(lineno, colno, filename)
        self.value = None

class OrNode(BaseNode):
    def __init__(self, left: BaseNode, right: BaseNode):
        super().__init__(left.lineno, left.colno, left.filename)
        self.left = left    # type: BaseNode
        self.right = right  # type: BaseNode

class AndNode(BaseNode):
    def __init__(self, left: BaseNode, right: BaseNode):
        super().__init__(left.lineno, left.colno, left.filename)
        self.left = left    # type: BaseNode
        self.right = right  # type: BaseNode

class ComparisonNode(BaseNode):
    def __init__(self, ctype: str, left: BaseNode, right: BaseNode):
        super().__init__(left.lineno, left.colno, left.filename)
        self.left = left    # type: BaseNode
        self.right = right  # type: BaseNode
        self.ctype = ctype  # type: str

class ArithmeticNode(BaseNode):
    def __init__(self, operation: str, left: BaseNode, right: BaseNode):
        super().__init__(left.lineno, left.colno, left.filename)
        self.left = left            # type: BaseNode
        self.right = right          # type: BaseNode
        self.operation = operation  # type: str

class NotNode(BaseNode):
    def __init__(self, token: Token[TV_TokenTypes], value: BaseNode):
        super().__init__(token.lineno, token.colno, token.filename)
        self.value = value  # type: BaseNode

class CodeBlockNode(BaseNode):
    def __init__(self, token: Token[TV_TokenTypes]):
        super().__init__(token.lineno, token.colno, token.filename)
        self.lines = []  # type: T.List[BaseNode]

class IndexNode(BaseNode):
    def __init__(self, iobject: BaseNode, index: BaseNode):
        super().__init__(iobject.lineno, iobject.colno, iobject.filename)
        self.iobject = iobject  # type: BaseNode
        self.index = index      # type: BaseNode

class MethodNode(BaseNode):
    def __init__(self, filename: str, lineno: int, colno: int, source_object: BaseNode, name: str, args: ArgumentNode):
        super().__init__(lineno, colno, filename)
        self.source_object = source_object  # type: BaseNode
        self.name = name                    # type: str
        assert isinstance(self.name, str)
        self.args = args                    # type: ArgumentNode

class FunctionNode(BaseNode):
    def __init__(self, filename: str, lineno: int, colno: int, end_lineno: int, end_colno: int, func_name: str, args: ArgumentNode):
        super().__init__(lineno, colno, filename, end_lineno=end_lineno, end_colno=end_colno)
        self.func_name = func_name  # type: str
        assert isinstance(func_name, str)
        self.args = args  # type: ArgumentNode

class AssignmentNode(BaseNode):
    def __init__(self, filename: str, lineno: int, colno: int, var_name: str, value: BaseNode):
        super().__init__(lineno, colno, filename)
        self.var_name = var_name  # type: str
        assert isinstance(var_name, str)
        self.value = value  # type: BaseNode

class PlusAssignmentNode(BaseNode):
    def __init__(self, filename: str, lineno: int, colno: int, var_name: str, value: BaseNode):
        super().__init__(lineno, colno, filename)
        self.var_name = var_name  # type: str
        assert isinstance(var_name, str)
        self.value = value  # type: BaseNode

class ForeachClauseNode(BaseNode):
    def __init__(self, token: Token, varnames: T.List[str], items: BaseNode, block: CodeBlockNode):
        super().__init__(token.lineno, token.colno, token.filename)
        self.varnames = varnames  # type: T.List[str]
        self.items = items        # type: BaseNode
        self.block = block        # type: CodeBlockNode

class IfNode(BaseNode):
    def __init__(self, linenode: BaseNode, condition: BaseNode, block: CodeBlockNode):
        super().__init__(linenode.lineno, linenode.colno, linenode.filename)
        self.condition = condition  # type: BaseNode
        self.block = block          # type: CodeBlockNode

class IfClauseNode(BaseNode):
    def __init__(self, linenode: BaseNode):
        super().__init__(linenode.lineno, linenode.colno, linenode.filename)
        self.ifs = []          # type: T.List[IfNode]
        self.elseblock = None  # type: T.Union[EmptyNode, CodeBlockNode]

class ParenthesizedNode(BaseNode):
    def __init__(self, inner: BaseNode, lineno: int, colno: int, end_lineno: int, end_colno: int):
        super().__init__(lineno, colno, inner.filename, end_lineno=end_lineno, end_colno=end_colno)
        self.inner = inner              # type: BaseNode

class UMinusNode(BaseNode):
    def __init__(self, current_location: Token, value: BaseNode):
        super().__init__(current_location.lineno, current_location.colno, current_location.filename)
        self.value = value  # type: BaseNode

class TernaryNode(BaseNode):
    def __init__(self, condition: BaseNode, trueblock: BaseNode, falseblock: BaseNode):
        super().__init__(condition.lineno, condition.colno, condition.filename)
        self.condition = condition    # type: BaseNode
        self.trueblock = trueblock    # type: BaseNode
        self.falseblock = falseblock  # type: BaseNode

comparison_map = {'equal': '==',
                  'nequal': '!=',
                  'lt': '<',
                  'le': '<=',
                  'gt': '>',
                  'ge': '>=',
                  'in': 'in',
                  'notin': 'not in',
                  }

# Recursive descent parser for Meson's definition language.
# Very basic apart from the fact that we have many precedence
# levels so there are not enough words to describe them all.
# Enter numbering:
#
# 1 assignment
# 2 or
# 3 and
# 4 comparison
# 5 arithmetic
# 6 negation
# 7 funcall, method call
# 8 parentheses
# 9 plain token

class Parser:
    def __init__(self, code: str, filename: str):
        self.lexer = Lexer(code)
        self.stream = self.lexer.lex(filename)
        self.current = Token('eof', '', 0, 0, 0, (0, 0), None)  # type: Token
        self.getsym()
        self.in_ternary = False
        self.stack = [] # type: T.List[Token]
        self.nodes = set() # type: T.Set[BaseNode]

    def begin(self) -> None:
        self.stack.append(self.current)

    def end(self, node: BaseNode) -> None:
        assert len(self.stack) > 0
        token = self.stack.pop()
        # print("%s: [%s:%s] -> [%s:%s] (%s %s)"%(type(node), token.lineno, token.colno, self.current.lineno, self.current.colno, token.bytespan, self.current.bytespan))
        node.bytespan = (token.bytespan[0], self.current.bytespan[0])
        self.nodes.add(node)

    def comments(self) -> T.List[Comment]:
        return self.lexer.comments

    def getsym(self) -> None:
        try:
            self.current = next(self.stream)
        except StopIteration:
            self.current = Token('eof', '', self.current.line_start, self.current.lineno, self.current.colno + self.current.bytespan[1] - self.current.bytespan[0], (0, 0), None)

    def getline(self) -> str:
        return self.lexer.getline(self.current.line_start)

    def accept(self, s: str) -> bool:
        if self.current.tid == s:
            self.getsym()
            return True
        return False

    def accept_any(self, tids: T.Tuple[str, ...]) -> str:
        tid = self.current.tid
        if tid in tids:
            self.getsym()
            return tid
        return ''

    def expect(self, s: str) -> bool:
        if self.accept(s):
            return True
        raise ParseException(f'Expecting {s} got {self.current.tid}.', self.getline(), self.current.lineno, self.current.colno)

    def block_expect(self, s: str, block_start: Token) -> bool:
        if self.accept(s):
            return True
        raise BlockParseException(f'Expecting {s} got {self.current.tid}.', self.getline(), self.current.lineno, self.current.colno, self.lexer.getline(block_start.line_start), block_start.lineno, block_start.colno)

    def parse(self) -> CodeBlockNode:
        block = self.codeblock()
        self.expect('eof')
        for s in self.stack:
            print(s)
        assert len(self.stack) == 0
        for c in self.lexer.comments:
            self.attach_comment(c)
        return block

    def attach_comment(self, comment: Comment) -> None:
        if len(self.nodes) == 0:
            return
        smallest_distance = 100000000000
        node = None
        for n in self.nodes:
            # Comment is before node
            if n.bytespan[0] > comment.bytespan[0]:
                continue
            # Comment is after node
            if n.bytespan[1] < comment.bytespan[0]:
                continue
            distance = n.bytespan[1] - n.bytespan[0]
            if smallest_distance > distance:
                smallest_distance = distance
                node = n
        if node is not None:
            node.comments.append(comment)
            return
        smallest_distance = 100000000000
        node = None
        # Now we try to attach the comment to nodes that are before it
        for n in self.nodes:
            # Comment is before node
            if n.bytespan[0] > comment.bytespan[0]:
                continue
            distance = n.bytespan[1] - comment.bytespan[0]
            if smallest_distance > distance:
                smallest_distance = distance
                node = n
        if node is not None:
            node.pre_comments.append(comment)
            return
        smallest_distance = 100000000000
        node = None
        # Now we try to attach the comment to nodes that are after it
        for n in self.nodes:
            # Comment is after node
            if comment.bytespan[1] < n.bytespan[0]:
                continue
            distance = comment.bytespan[1] - n.bytespan[0]
            if smallest_distance > distance:
                smallest_distance = distance
                node = n
        if node is not None:
            node.post_comments.append(comment)
            return
        assert node is not None

    def statement(self) -> BaseNode:
        self.begin()
        e = self.e1()
        self.end(e)
        return e

    def e1(self) -> BaseNode:
        self.begin()
        left = self.e2()
        if self.accept('plusassign'):
            value = self.e1()
            if not isinstance(left, IdNode):
                raise ParseException('Plusassignment target must be an id.', self.getline(), left.lineno, left.colno)
            assert isinstance(left.value, str)
            e = PlusAssignmentNode(left.filename, left.lineno, left.colno, left.value, value)
            self.end(e)
            return e
        elif self.accept('assign'):
            value = self.e1()
            if not isinstance(left, IdNode):
                raise ParseException('Assignment target must be an id.',
                                     self.getline(), left.lineno, left.colno)
            assert isinstance(left.value, str)
            f = AssignmentNode(left.filename, left.lineno, left.colno, left.value, value)
            self.end(f)
            return f
        elif self.accept('questionmark'):
            if self.in_ternary:
                raise ParseException('Nested ternary operators are not allowed.',
                                     self.getline(), left.lineno, left.colno)
            self.in_ternary = True
            trueblock = self.e1()
            self.expect('colon')
            falseblock = self.e1()
            self.in_ternary = False
            g = TernaryNode(left, trueblock, falseblock)
            self.end(g)
            return g
        self.end(left)
        return left

    def e2(self) -> BaseNode:
        self.begin()
        left = self.e3()
        started = False
        while self.accept('or'):
            started = True
            if isinstance(left, EmptyNode):
                raise ParseException('Invalid or clause.',
                                     self.getline(), left.lineno, left.colno)
            x1 = OrNode(left, self.e3())
            self.end(x1)
            left = x1
            started = False
            self.begin()
        if not started:
            self.end(left)
        return left

    def e3(self) -> BaseNode:
        self.begin()
        left = self.e4()
        started = False
        while self.accept('and'):
            if isinstance(left, EmptyNode):
                raise ParseException('Invalid and clause.',
                                     self.getline(), left.lineno, left.colno)
            x1 = AndNode(left, self.e4())
            self.end(x1)
            left = x1
            started = False
            self.begin()
        if not started:
            self.end(left)
        return left

    def e4(self) -> BaseNode:
        self.begin()
        left = self.e5()
        for nodename, operator_type in comparison_map.items():
            if self.accept(nodename):
                x = ComparisonNode(operator_type, left, self.e5())
                self.end(x)
                return x
        if self.accept('not') and self.accept('in'):
            x = ComparisonNode('notin', left, self.e5())
            self.end(x)
            return x
        self.end(left)
        return left

    def e5(self) -> BaseNode:
        return self.e5addsub()

    def e5addsub(self) -> BaseNode:
        self.begin()
        op_map = {
            'plus': 'add',
            'dash': 'sub',
        }
        left = self.e5muldiv()
        while True:
            op = self.accept_any(tuple(op_map.keys()))
            if op:
                x1 = ArithmeticNode(op_map[op], left, self.e5muldiv())
                self.end(x1)
                left = x1
                self.begin()
            else:
                break
        self.end(left)
        return left

    def e5muldiv(self) -> BaseNode:
        self.begin()
        op_map = {
            'percent': 'mod',
            'star': 'mul',
            'fslash': 'div',
        }
        left = self.e6()
        while True:
            op = self.accept_any(tuple(op_map.keys()))
            if op:
                x1 = ArithmeticNode(op_map[op], left, self.e6())
                self.end(x1)
                left = x1
                self.begin()
            else:
                break
        self.end(left)
        return left

    def e6(self) -> BaseNode:
        self.begin()
        if self.accept('not'):
            x = NotNode(self.current, self.e7())
            self.end(x)
            return x
        if self.accept('dash'):
            x1 = UMinusNode(self.current, self.e7())
            self.end(x1)
            return x1
        x2 = self.e7()
        self.end(x2)
        return x2

    def e7(self) -> BaseNode:
        self.begin()
        left = self.e8()
        block_start = self.current
        if self.accept('lparen'):
            args = self.args()
            self.block_expect('rparen', block_start)
            if not isinstance(left, IdNode):
                raise ParseException('Function call must be applied to plain id',
                                     self.getline(), left.lineno, left.colno)
            assert isinstance(left.value, str)
            x1 = FunctionNode(left.filename, left.lineno, left.colno, self.current.lineno, self.current.colno, left.value, args)
            self.end(left)
            left = x1
            self.begin()
        go_again = True
        while go_again:
            go_again = False
            if self.accept('dot'):
                go_again = True
                x2 = self.method_call(left)
                self.end(left)
                left = x2
                self.begin()
            if self.accept('lbracket'):
                go_again = True
                x3 = self.index_call(left)
                self.end(left)
                left = x3
                self.begin()
        self.end(left)
        return left

    def e8(self) -> BaseNode:
        self.begin()
        block_start = self.current
        if self.accept('lparen'):
            e = self.statement()
            self.block_expect('rparen', block_start)
            e1 = ParenthesizedNode(e, block_start.lineno, block_start.colno, self.current.lineno, self.current.colno)
            self.end(e1)
            return e1
        elif self.accept('lbracket'):
            args = self.args()
            self.block_expect('rbracket', block_start)
            x1 = ArrayNode(args, block_start.lineno, block_start.colno, self.current.lineno, self.current.colno)
            self.end(x1)
            return x1
        elif self.accept('lcurl'):
            key_values = self.key_values()
            self.block_expect('rcurl', block_start)
            x2 = DictNode(key_values, block_start.lineno, block_start.colno, self.current.lineno, self.current.colno)
            self.end(x2)
            return x2
        else:
            x3 = self.e9()
            self.end(x3)
            return x3

    def e9(self) -> BaseNode:
        self.begin()
        t = self.current
        if self.accept('true'):
            t.value = True
            x1 = BooleanNode(t)
            self.end(x1)
            return x1
        if self.accept('false'):
            t.value = False
            x2 = BooleanNode(t)
            self.end(x2)
            return x2
        if self.accept('id'):
            x3 = IdNode(t)
            self.end(x3)
            return x3
        if self.accept('number'):
            x4 = NumberNode(t)
            self.end(x4)
            return x4
        if self.accept('string'):
            x5 = StringNode(t)
            self.end(x5)
            return x5
        if self.accept('fstring'):
            x6 = FormatStringNode(t)
            self.end(x6)
            return x6
        if self.accept('multiline_fstring'):
            x7 = MultilineFormatStringNode(t)
            self.end(x7)
            return x7
        x8 = EmptyNode(self.current.lineno, self.current.colno, self.current.filename)
        self.end(x8)
        return x8

    def key_values(self) -> ArgumentNode:
        self.begin()
        s = self.statement()  # type: BaseNode
        a = ArgumentNode(self.current)

        while not isinstance(s, EmptyNode):
            if self.accept('colon'):
                a.set_kwarg_no_check(s, self.statement())
                potential = self.current
                if not self.accept('comma'):
                    self.end(a)
                    return a
                a.commas.append(potential)
            else:
                raise ParseException('Only key:value pairs are valid in dict construction.',
                                     self.getline(), s.lineno, s.colno)
            s = self.statement()
        self.end(a)
        return a

    def args(self) -> ArgumentNode:
        self.begin()
        s = self.statement()  # type: BaseNode
        a = ArgumentNode(self.current)

        while not isinstance(s, EmptyNode):
            potential = self.current
            if self.accept('comma'):
                a.commas.append(potential)
                a.append(s)
            elif self.accept('colon'):
                if not isinstance(s, IdNode):
                    raise ParseException('Dictionary key must be a plain identifier.',
                                         self.getline(), s.lineno, s.colno)
                a.set_kwarg(s, self.statement())
                potential = self.current
                if not self.accept('comma'):
                    self.end(a)
                    return a
                a.commas.append(potential)
            else:
                a.append(s)
                self.end(a)
                return a
            s = self.statement()
        self.end(a)
        return a

    def method_call(self, source_object: BaseNode) -> MethodNode:
        self.begin()
        methodname = self.e9()
        if not isinstance(methodname, IdNode):
            raise ParseException('Method name must be plain id',
                                 self.getline(), self.current.lineno, self.current.colno)
        assert isinstance(methodname.value, str)
        self.expect('lparen')
        args = self.args()
        self.expect('rparen')
        method = MethodNode(methodname.filename, methodname.lineno, methodname.colno, source_object, methodname.value, args)
        if self.accept('dot'):
            x1 = self.method_call(method)
            self.end(x1)
            return x1
        self.end(method)
        return method

    def index_call(self, source_object: BaseNode) -> IndexNode:
        self.begin()
        index_statement = self.statement()
        self.expect('rbracket')
        x1 = IndexNode(source_object, index_statement)
        self.end(x1)
        return x1

    def foreachblock(self) -> ForeachClauseNode:
        self.begin()
        t = self.current
        self.expect('id')
        assert isinstance(t.value, str)
        varname = t
        varnames = [t.value]  # type: T.List[str]

        if self.accept('comma'):
            t = self.current
            self.expect('id')
            assert isinstance(t.value, str)
            varnames.append(t.value)

        self.expect('colon')
        items = self.statement()
        block = self.codeblock()
        x1 = ForeachClauseNode(varname, varnames, items, block)
        self.end(x1)
        return x1

    def ifblock(self) -> IfClauseNode:
        self.begin()
        condition = self.statement()
        clause = IfClauseNode(condition)
        self.expect('eol')
        block = self.codeblock()
        self.begin()
        i = IfNode(clause, condition, block)
        self.end(i)
        clause.ifs.append(i)
        self.elseifblock(clause)
        clause.elseblock = self.elseblock()
        self.end(clause)
        return clause

    def elseifblock(self, clause: IfClauseNode) -> None:
        while self.accept('elif'):
            self.begin()
            s = self.statement()
            self.expect('eol')
            b = self.codeblock()
            x1 = IfNode(s, s, b)
            self.end(x1)
            clause.ifs.append(x1)

    def elseblock(self) -> T.Union[CodeBlockNode, EmptyNode]:
        if self.accept('else'):
            self.expect('eol')
            return self.codeblock()
        self.begin()
        x1 = EmptyNode(self.current.lineno, self.current.colno, self.current.filename)
        self.end(x1)
        return x1

    def line(self) -> BaseNode:
        block_start = self.current
        self.begin()
        if self.current == 'eol':
            x1 = EmptyNode(self.current.lineno, self.current.colno, self.current.filename)
            self.end(x1)
            return x1
        if self.accept('if'):
            ifblock = self.ifblock()
            self.block_expect('endif', block_start)
            self.end(ifblock)
            return ifblock
        if self.accept('foreach'):
            forblock = self.foreachblock()
            self.block_expect('endforeach', block_start)
            self.end(forblock)
            return forblock
        if self.accept('continue'):
            x2 = ContinueNode(self.current)
            self.end(x2)
            return x2
        if self.accept('break'):
            x3 = BreakNode(self.current)
            self.end(x3)
            return x3
        s = self.statement()
        self.end(s)
        return s

    def codeblock(self) -> CodeBlockNode:
        self.begin()
        block = CodeBlockNode(self.current)
        cond = True
        while cond:
            curline = self.line()
            if not isinstance(curline, EmptyNode):
                block.lines.append(curline)
            cond = self.accept('eol')
        self.end(block)
        return block
