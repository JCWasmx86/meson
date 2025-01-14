# Copyright 2022 The Meson development team

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This class contains the basic functionality needed to format code
import re
from .. import mparser
from . import AstVisitor
import typing as T

arithmic_map = {
    'add': '+',
    'sub': '-',
    'mod': '%',
    'mul': '*',
    'div': '/'
}

class AstFormatter2(AstVisitor):
    def __init__(self,  lines: T.List[str], config):
        self.lines = []
        self.indentstr = config['indent_by']
        self.currindent = ''
        self.currline = ''
        self.old_lines = lines
        self.config = config

    def end(self):
        self.lines.append(self.currline)
        for i, l in enumerate(self.lines):
            if l.strip() == '':
                self.lines[i] = ''

    def append(self, to_append):
        self.currline += to_append

    def force_linebreak(self):
        if self.currline.strip() != '':
            self.lines.append(self.currline)
            self.currline = self.currindent

    def visit_BooleanNode(self, node: mparser.BooleanNode) -> None:
        self.append('true' if node.value else 'false')

    def visit_IdNode(self, node: mparser.IdNode) -> None:
        assert isinstance(node.value, str)
        self.append(node.value)

    def visit_NumberNode(self, node: mparser.NumberNode) -> None:
        self.append(str(node.value))

    def escape(self, val: str) -> str:
        return val.translate(str.maketrans({'\'': '\\\'',
                                            '\\': '\\\\',
                                            '\n': '\\n'}))

    def visit_StringNode(self, node: mparser.StringNode) -> None:
        assert isinstance(node.value, str)
        self.append("'" + self.escape(node.value) + "'")

    def visit_FormatStringNode(self, node: mparser.FormatStringNode) -> None:
        assert isinstance(node.value, str)
        self.append("f'" + node.value + "'")

    def visit_ContinueNode(self, node: mparser.ContinueNode) -> None:
        self.force_linebreak()
        self.append('continue')
        self.force_linebreak()

    def visit_BreakNode(self, node: mparser.BreakNode) -> None:
        self.force_linebreak()
        self.append('break')
        self.force_linebreak()

    def visit_ArrayNode(self, node: mparser.ArrayNode) -> None:
        self.append('[')
        num_elements = len(node.args.arguments)
        if self.config['space_array'] and num_elements != 0:
            self.append(' ')
        node.args.accept(self)
        if self.config['space_array'] and num_elements != 0:
            self.append(' ')
        self.append(']')

    def visit_DictNode(self, node: mparser.DictNode) -> None:
        self.append('{')
        node.args.accept(self)
        self.append('}')

    def visit_OrNode(self, node: mparser.OrNode) -> None:
        node.left.accept(self)
        self.append(' or ')
        node.right.accept(self)

    def visit_AndNode(self, node: mparser.AndNode) -> None:
        node.left.accept(self)
        self.append(' and ')
        node.right.accept(self)

    def visit_ComparisonNode(self, node: mparser.ComparisonNode) -> None:
        node.left.accept(self)
        self.append(' ' + (node.ctype if node.ctype != 'notin' else 'not in') + ' ')
        node.right.accept(self)

    def visit_ArithmeticNode(self, node: mparser.ArithmeticNode) -> None:
        node.left.accept(self)
        self.append(' ' + arithmic_map[node.operation] + ' ')
        node.right.accept(self)

    def visit_NotNode(self, node: mparser.NotNode) -> None:
        self.append('not ')
        node.value.accept(self)

    def visit_CodeBlockNode(self, node: mparser.CodeBlockNode) -> None:
        idx = 0
        for i in node.lines:
            i.accept(self)
            self.force_linebreak()
            idx += 1

    def visit_IndexNode(self, node: mparser.IndexNode) -> None:
        node.iobject.accept(self)
        self.append('[')
        if self.config['space_array']:
            self.append(' ')
        node.index.accept(self)
        if self.config['space_array']:
            self.append(' ')
        self.append(']')

    def visit_MethodNode(self, node: mparser.MethodNode) -> None:
        node.source_object.accept(self)
        self.append('.' + node.name + '(')
        if len(node.args.arguments) != 0 or len(node.args.kwargs) != 0:
            args = node.args
            args.accept(self)
        self.append(')')

    def visit_FunctionNode(self, node: mparser.FunctionNode) -> None:
        self.append(node.func_name + '(')
        if len(node.args.arguments) != 0 or len(node.args.kwargs) != 0:
            args = node.args
            args.accept(self)
        self.append(')')

    def visit_AssignmentNode(self, node: mparser.AssignmentNode) -> None:
        self.append(node.var_name + ' = ')
        node.value.accept(self)

    def visit_PlusAssignmentNode(self, node: mparser.PlusAssignmentNode) -> None:
        self.append(node.var_name + ' += ')
        node.value.accept(self)

    def visit_UMinusNode(self, node: mparser.UMinusNode) -> None:
        self.append('-')
        node.value.accept(self)

    def visit_IfNode(self, node: mparser.IfNode) -> None:
        node.condition.accept(self)
        tmp = self.currindent
        self.currindent += self.indentstr
        self.force_linebreak()
        node.block.accept(self)
        self.currindent = tmp

    def visit_ForeachClauseNode(self, node: mparser.ForeachClauseNode) -> None:
        varnames = list(node.varnames)
        tmp = self.currindent
        self.append('foreach ')
        self.append(', '.join(varnames))
        self.append(' : ')
        node.items.accept(self)
        self.currindent += self.indentstr
        self.force_linebreak()
        node.block.accept(self)
        self.currindent = tmp
        self.force_linebreak()
        self.currline = self.currindent
        self.append('endforeach')

    def visit_IfClauseNode(self, node: mparser.IfClauseNode) -> None:
        prefix = ''
        tmp = self.currindent
        for i in node.ifs:
            self.currindent = tmp
            self.currline = self.currindent
            self.append(prefix + 'if ')
            prefix = 'el'
            i.accept(self)
            self.currindent = tmp
            self.currline = self.currindent
        if not isinstance(node.elseblock, mparser.EmptyNode):
            self.append('else')
            self.currindent += self.indentstr
            self.force_linebreak()
            node.elseblock.accept(self)
            self.currindent = tmp
            self.force_linebreak()
        self.currindent = tmp
        self.currline = self.currindent
        self.append('endif')
        self.force_linebreak()

    def visit_TernaryNode(self, node: mparser.TernaryNode) -> None:
        node.condition.accept(self)
        self.append(' ? ')
        node.trueblock.accept(self)
        self.append(' : ')
        node.falseblock.accept(self)

    def visit_ArgumentNode(self, node: mparser.ArgumentNode) -> None:
        for i in node.arguments:
            i.accept(self)
            self.append(', ')
        wide_colon = self.config['wide_colon']
        tmp = self.currindent
        self.currindent += self.indentstr
        idx = 0
        for key, val in node.kwargs.items():
            self.force_linebreak()
            key.accept(self)
            if not wide_colon:
                self.append(': ')
            else:
                self.append(' : ')
            val.accept(self)
            if idx == len(node.kwargs) - 1:
                self.currindent = tmp
                self.force_linebreak()
            else:
                self.append(',')
            idx += 1
        self.currindent = tmp
        self.currline = re.sub(r', $', '', self.currline)

    def visit_ParenthesizedNode(self, node: mparser.ParenthesizedNode) -> None:
        self.append('(')
        node.inner.accept(self)
        self.append(')')
