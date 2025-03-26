"""
Functions to automate the creation of documentation of Biolink classes written from Koza transforms.
"""

import dataclasses
from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, Sequence

import jedi
import libcst as cst
import libcst.matchers as m
from jedi.api.classes import Name
from libcst.metadata import CodeRange, PositionProvider

# The sigial that marks that the following line contains a biolink class that should be documented.
CLASS_DOCUMENTATION_MARKER = "# !DocumentClass"

# A matcher for statements that have the above sigil preceding them.
biolink_statement_pattern = m.SimpleStatementLine(
    leading_lines=[
        m.EmptyLine(
            comment=m.Comment(
                value=m.MatchIfTrue(lambda text: text.startswith(CLASS_DOCUMENTATION_MARKER)),
            ),
        ),
    ],
)

# A matcher for accessing a field in a koza transform where the data is stored in a variable called `row`. For
# example: row["Field X"].
row_access_literal = m.Subscript(
    value=m.Name(value="row"),
    slice=[
        m.SubscriptElement(
            slice=m.Index(
                value=m.SaveMatchedNode(m.SimpleString(), "source"),
            ),
        ),
    ],
)

# A matcher for accessing a field in a koza transform where the data is stored in a variable called `row`, but where
# the field is stored in a variable. For example: row[x].
# Note: This is not currently used
row_access_name = m.Subscript(
    value=m.Name(value="row"),
    slice=[
        m.SubscriptElement(
            slice=m.Index(
                value=m.SaveMatchedNode(m.Name(), "source"),
            ),
        ),
    ],
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class DocumentedFieldAnnotations:
    """
    A dataclass representing annotations added to biolink class parameters.

    There are three annotations supported:
        1. Note - Documentation about curitorial decisions.
        2. Source - An indication of the source of the parameter in a data file. This is able to be inferred
           automatically (see `find_kw_source`), but the heuristics there are not perfect. This can take multiple
           annotations if necessary.
        3. Type - The type expected by the parameter. (Currently unused).

    Annotations must appear directly above the parameter declaration in the form:
        # annotation_name: annotation_content

    Annotation content can span multiple lines. The parser will slurp up all consecutive lines for an annotation
    until another annotation appears. For example:

        NamedThing(
            id="ex:foobar",

            # note: this has been deprecated since 2019. See [this explanation](http://example.com/) for
            # more information
            deprecated: True,

            # source: Column B
            # source: Column C
            full_name=baz,
        )

    This class has two annotations. `deprecated` has a `note` annotation that spans two lines, and `full_name` has
    two `source` annotations.

    :param note: Curatorial decisions about the parameter.
    :param source: The column/record in the source file from which this parameter was derived.
    :param _type: The type of this parameter (currently unused).
    """

    note: str | None = None
    source: str | None = None
    _type: str | None = None

    @classmethod
    def from_comment_strs(cls, comments: list[str]) -> "DocumentedFieldAnnotations":
        """Given a list of comment tokens, create a ParameterAnnotations object."""
        metadata: dict[str, str] = {}
        cur_group = None
        for comment_str in comments:
            if comment_str.startswith("# type: "):
                metadata["type"] = comment_str.replace("# type: ", "")
                cur_group = "type"
                continue
            if comment_str.startswith("# source: "):
                metadata["source"] = comment_str.replace("# source: ", "")
                cur_group = "source"
                continue
            elif comment_str.startswith("# note: "):
                metadata["note"] = comment_str.replace("# note: ", "")
                cur_group = "note"
                continue
            elif cur_group is None:
                continue
            else:
                existing = metadata[cur_group]
                metadata[cur_group] = existing + " " + comment_str[2:]

        return cls(
            _type=metadata.get("type", None),
            note=metadata.get("note", None),
            source=metadata.get("source", None),
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class DocumentedField:
    """
    A documented field within a biolink class.

    :param name: The name of the field.
    :param parsed_source: The inferred source of the value of the field.
    :param annotations: The annotations for the field.
    """

    name: str
    parsed_source: list[str] | None
    constant: str | None
    annotations: DocumentedFieldAnnotations


@dataclasses.dataclass(frozen=True, kw_only=True)
class DocumentedClass:
    """
    A documented biolink class.

    :param name: The name of the class.
    :param fields: The fields in the class.
    """

    name: str
    fields: list[DocumentedField]


class DocumentedStatementsVisitor(m.MatcherDecoratableVisitor):
    """
    A visitor that will extract classes marked to be documented.

    :param script: An instantiated Jedi script to be used for static analysis when necessary.
    """

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, script: jedi.Script):
        self.script = script
        self.call_pos = 0
        self.source_assigns_by_row: DefaultDict[int, list[str]] = defaultdict(list)
        self.documented_classes: list[DocumentedClass] = []

        super().__init__()

    def _get_code_range(self, node: cst.CSTNode) -> CodeRange:
        """
        Helper method for getting a code range of a node to placate pyright's typing checking.

        See <https://github.com/Instagram/LibCST/issues/1107>.

        :param node: The node from which to extract CodeRange metadata.
        """
        return cst.ensure_type(self.get_metadata(PositionProvider, node), CodeRange)

    def _get_arg_annotations(
        self,
        comments: Sequence[cst.Comment],
        node: cst.Arg,
    ) -> DocumentedFieldAnnotations:
        """
        For an keyword argument when creating a biolink class, retrieve all annotations for that keyword.

        To get these annotations (which appear in comments above the kwarg), we need to manually search for them in
        cst.Comment nodes, since in the current version of libcst, whitespace before an argument does not belong to
        the argument node.

        See <https://github.com/Instagram/LibCST/issues/1157>.

        :param comments: The list of all comment nodes in the parent Call statement.
        :param node: The kwarg statement from which to extract annotations.
        """
        arg_range = self._get_code_range(node)
        arg_comments: list[str] = []
        pos = arg_range.start.line - 1
        for comment in reversed(comments):
            comment_range = self._get_code_range(comment)
            if comment_range.start.line > pos:
                continue
            if comment_range.start.line < pos:
                break
            arg_comments.insert(0, cst.ensure_type(comment, cst.Comment).value)
            pos -= 1
        return DocumentedFieldAnnotations.from_comment_strs(arg_comments)

    def _find_arg_sources(self, node: cst.Arg) -> list[str]:
        """
        Attempt to find all of the fields from the data used to construct a given kwarg.

        There are currently two ways this data will be retrieved.

        First, if a kwarg directly references the source column in a variable named row. From this code:

            Gene(
                label=row["Name"]
            )

        The arg source for `label` will be "Name". (Note that row["Name"] only has to appear somewhere in the target of
        the assignment. It could, for instance, be an argument to a function call).

        Second, if the kwarg references a variable whose definition directly references the source column. (Note, this
        only follows the variable one step) From this code:

            name = process_name(row["Name"])
            Gene(
                label=name
            )

        The definition of the `name` variable will be analyzed, and the arg source for `label` will be "name".

        :param node: The kwarg node to analyze for a source field.
        """
        sources: list[str] = []

        inline_source_literal = m.extractall(node.value, row_access_literal)
        if inline_source_literal:
            for literal in inline_source_literal:
                value = literal["source"].value[1:-1]  # type: ignore
                assert isinstance(value, str)
                sources.append(value)

        is_defined_name = m.matches(node.value, m.Name())
        if is_defined_name:
            name_range = self._get_code_range(node.value)
            assignment = self.script.goto(name_range.start.line, name_range.start.column)[0]
            assert isinstance(assignment, Name)
            assert isinstance(assignment.line, int)
            sources += self.source_assigns_by_row[assignment.line]

        return sources

    def _get_arg_const(self, node: cst.Arg):
        match node.value:
            case cst.SimpleString(value=value):
                return value[1:-1]

            case cst.List(elements=[cst.Element(value=cst.SimpleString(value=value))]):
                return value[1:-1]
            case _:
                return None

    def _parse_arg(self, comments: list[cst.Comment], node: cst.Arg) -> DocumentedField:
        """
        Given a kwarg node, construct a DocumentedField class for it.

        :param comments: A list of comments in the parent Call node.
        :param node: The kwarg node to parse.
        """
        annotations = self._get_arg_annotations(comments, node)
        source = self._find_arg_sources(node)
        constant = self._get_arg_const(node)
        assert isinstance(node.keyword, cst.Name)

        return DocumentedField(
            name=node.keyword.value,
            parsed_source=source or None,
            annotations=annotations,
            constant=constant,
        )

    @m.call_if_not_inside(biolink_statement_pattern)
    def visit_Assign(self, node: cst.Assign) -> None:
        """
        Before any marked documentation classes, store any assignments that reference `row` data.

        This is used later to track whether a variable referenced in a kwarg was previously defined from a field in a
        data source.

        Assignments referencing a row are stored in the visitor class's internal state by the row number.
        """
        assigns = m.extractall(node, row_access_literal)
        for assign in assigns:
            source_literal_node = assign["source"]
            if not isinstance(source_literal_node, cst.SimpleString):
                continue
            row = self._get_code_range(source_literal_node).start.line
            self.source_assigns_by_row[row].append(source_literal_node.value[1:-1])

    @m.call_if_inside(biolink_statement_pattern)
    def visit_Call(self, node: cst.Call) -> None:
        """
        Parse biolink classes that have been marked to document.

        This visitor looks for Call nodes at the top level of a parse tree underneath the documentation marker. So in
        this case:

            a = Gene(name=get_name())

        The `Gene` call node will be targeted, but the `get_name` call node (which is farther down the tree) will not.

        """

        match node.func:
            case cst.Name():
                call_range = self._get_code_range(node.func)
            case cst.Attribute():
                call_range = self._get_code_range(node.func.attr)
            case _:
                return

        inferred_type = self.script.infer(call_range.start.line, call_range.start.column)[0]
        assert isinstance(inferred_type, Name)

        is_biolink_class = (
            inferred_type.full_name is not None
            and inferred_type.full_name.startswith("biolink_model.datamodel.pydanticmodel_v2.")
            and inferred_type.description.startswith("class ")
        )

        if not is_biolink_class:
            return

        comments = [cst.ensure_type(comment, cst.Comment) for comment in m.findall(node, m.Comment())]
        parameters = [self._parse_arg(comments, arg) for arg in node.args]
        documentated_class = DocumentedClass(
            name=inferred_type.description[6:],
            fields=parameters,
        )
        self.documented_classes.append(documentated_class)


def extract_biolink_documentation(script_path: Path) -> list[DocumentedClass]:
    with script_path.open("r") as fp:
        module = cst.parse_module(fp.read())

    project = jedi.get_default_project(script_path)
    environment = jedi.create_environment(path=project.path / ".venv")
    script = jedi.Script(path=script_path, environment=environment)

    wrapper = cst.MetadataWrapper(module)
    statements_visitor = DocumentedStatementsVisitor(script)
    wrapper.visit(statements_visitor)

    return statements_visitor.documented_classes
