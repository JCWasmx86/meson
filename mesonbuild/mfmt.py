import argparse
from . import coredata, mparser
from . import mesonlib
from .ast import AstFormatter

def add_arguments(parser: argparse.ArgumentParser) -> None:
    coredata.register_builtin_arguments(parser)
    parser.add_argument('files', nargs=argparse.REMAINDER,
                        help='files to format')

def run(options: argparse.Namespace) -> int:
    for filename in options.files:
        with open(filename, encoding='utf-8') as f:
            code = f.read()
        assert isinstance(code, str)
        try:
            codeblock = mparser.Parser(code, filename).parse()
        except mesonlib.MesonException as me:
            me.file = filename
            raise me
        formatter = AstFormatter()
        codeblock.accept(formatter)
        formatter.end()
        for line in formatter.lines:
            print(line)
        print(dir(codeblock))
