from typing import Union, cast

import libcst as cst
import libcst.matchers as m


def attribute(value: str, attr: str) -> m.Attribute:
    return m.Attribute(
        value=m.Name(value=value),
        attr=m.Name(value=attr),
    )


# while (row := koza_app.get_row()) is not None:
while_row_statement = m.While(
    test=m.Comparison(
        left=m.NamedExpr(
            target=m.Name(value="row"),
            value=m.Call(attribute("koza_app", "get_row")),
            whitespace_before_walrus=m.SimpleWhitespace(),
            whitespace_after_walrus=m.SimpleWhitespace(),
        ),
    ),
)

# from koza.cli_utils import get_koza_app
get_koza_app_import = m.ImportFrom(
    module=attribute("koza", "cli_utils"),
    names=[
        m.ImportAlias(name=m.Name(value="get_koza_app")),
    ],
)

# koza_app = get_koza_app("app_name")
koza_app_assign = m.Assign(
    targets=[
        m.AssignTarget(target=m.Name(value="koza_app")),
    ],
    value=m.Call(
        func=m.Name(value="get_koza_app"),
    ),
)

# map = koza_app.get_map("app_name")
koza_map_assign = m.Assign(
    targets=[
        m.AssignTarget(
            target=m.SaveMatchedNode(m.Name(), name="map_var_name"),
        )
    ],
    value=m.Call(
        func=attribute("koza_app", "get_map"),
        args=[m.Arg(value=m.SaveMatchedNode(m.SimpleString(), name="map_name"))],
    ),
)

# koza_app.write(a, b, c)
koza_app_write = m.Call(
    func=m.Attribute(
        value=m.Name(value="koza_app"),
        attr=m.Name(value="write"),
    ),
)


class TransformTransformFunction(cst.CSTTransformer):
    def __init__(self, function_body: cst.CSTNode) -> None:
        self.function_body = function_body

    def leave_FunctionDef(self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef) -> cst.FunctionDef:
        return updated_node.with_changes(body=self.function_body)


def create_transform_fn(body: cst.CSTNode) -> cst.FunctionDef:
    transform_fn_code = "def transform_record(koza: Koza, record: dict[str, Any]): pass"
    tree = cst.parse_statement(transform_fn_code)
    return cast(cst.FunctionDef, tree.visit(TransformTransformFunction(body)))


class KozaVisitor(m.MatcherDecoratableTransformer):
    def __init__(self) -> None:
        self.maps: dict[str, str] = {}
        super().__init__()

    @m.visit(koza_map_assign)
    def save_map(self, node: cst.Assign) -> None:
        """
        Keep track of all the maps that are used in the transform.
        """
        results = m.extract(node, koza_map_assign) or {}
        map_name_node = cast(cst.SimpleString, results["map_name"])
        map_var_node = cast(cst.Name, results["map_var_name"])
        self.maps[map_var_node.value] = map_name_node.value

    @m.leave(while_row_statement)
    def insert_function_transformer(self, original_node: cst.While, updated_node: cst.While) -> cst.FunctionDef:
        """
        Replace `while` method of looping over rows with a `transform_record` function.
        """
        new_node = create_transform_fn(updated_node.body)
        return new_node.with_changes(leading_lines=updated_node.leading_lines)

    @m.leave(m.Name(value="row"))
    def replace_row_with_record(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
        """
        Use `record` as a variable name instead of `row`.`
        """
        return updated_node.with_changes(value="record")

    @m.leave(m.Subscript())
    def replace_map_subscript(
        self, original_node: cst.Subscript, updated_node: cst.Subscript
    ) -> Union[cst.Subscript, cst.Call]:
        """
        Use `koza.lookup(term, map_name)` for accessing maps rather than map[term].
        """
        match updated_node.value:
            case cst.Name(value=map_var_name) if map_var_name in self.maps:
                lookup_seq = updated_node.slice

                if len(lookup_seq) != 1:
                    return updated_node

                lookup = lookup_seq[0].slice
                if not isinstance(lookup, cst.Index):
                    return updated_node

                return cst.Call(
                    func=cst.Attribute(
                        value=cst.Name("koza"),
                        attr=cst.Name("lookup"),
                    ),
                    args=[
                        cst.Arg(value=lookup.value),
                        cst.Arg(value=cst.SimpleString(value=self.maps[map_var_name])),
                    ],
                )
            case _:
                return updated_node

    @m.leave(m.Call(func=m.Attribute(attr=m.Name(value="get"))))
    def replace_map_get(self, original_node: cst.Call, updated_node: cst.Call) -> cst.Call:
        """
        Use `koza.lookup(term, map_name)` for accessing maps rather than map.get(term).
        """
        match updated_node.func:
            case cst.Attribute(value=cst.Name(value=map_var_name)) if map_var_name in self.maps:
                args = updated_node.args
                if len(args) != 1:
                    return updated_node

                return cst.Call(
                    func=cst.Attribute(
                        value=cst.Name("koza"),
                        attr=cst.Name("lookup"),
                    ),
                    args=[
                        args[0],
                        cst.Arg(value=cst.SimpleString(value=self.maps[map_var_name])),
                    ],
                )
            case _:
                return updated_node

    @m.leave(get_koza_app_import)
    @m.leave(koza_app_assign)
    @m.leave(koza_map_assign)
    def remove_node(self, original_node: cst.CSTNode, updated_node: cst.CSTNode) -> cst.RemovalSentinel:
        """
        Remove now-unused nodes.
        """
        return cst.RemoveFromParent()

    @m.call_if_inside(koza_app_write)
    @m.leave(m.Name(value="koza_app"))
    def replace_koza_app_write(self, original_node: cst.Name, updated_node: cst.Name) -> cst.Name:
        """
        Replace `koza_app.write` with `koza.write`.
        """
        return updated_node.with_changes(value="koza")


def transform_koza_code(code: str) -> cst.Module:
    """
    Given the code of a koza transform, update it to the new API.
    """
    tree = cst.parse_module(code)
    visitor = KozaVisitor()
    return tree.visit(visitor)


if __name__ == "__main__":
    import sys

    with open(sys.argv[1], "r") as fp:
        modified_code = transform_koza_code(fp.read())

    print(modified_code.code)
