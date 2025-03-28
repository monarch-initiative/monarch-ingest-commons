# ruff: noqa: ANN201

import tempfile
from pathlib import Path

from monarch_ingest_commons.biolink_documentation import extract_biolink_documentation

VENV_PATH = Path(__file__).parent / "../.venv"


def extract_from_str(contents: str):
    with tempfile.NamedTemporaryFile() as fp:
        fp.write(contents.strip().encode())
        fp.flush()
        classes = extract_biolink_documentation(Path(fp.name))
    return classes


def test_extract_biolink_class():
    classes = extract_from_str(
        """
from biolink_model.datamodel.pydanticmodel_v2 import Gene

def main():
    # !DocumentClass
    gene = Gene()
        """
    )

    assert len(classes) == 1


def test_extract_biolink_class_from_attr():
    classes = extract_from_str(
        """
import biolink_model.datamodel.pydanticmodel_v2 as biolink

def main():
    # !DocumentClass
    gene = biolink.Gene()
        """
    )

    assert len(classes) == 1


def test_extract_biolink_class_from_variable():
    classes = extract_from_str(
        """
from biolink_model.datamodel.pydanticmodel_v2 import Gene

def main():
    alias = Gene

    # !DocumentClass
    gene = alias()
        """
    )

    assert len(classes) == 1
    assert classes[0].name == "Gene"


def test_non_biolink_not_extracted():
    classes = extract_from_str(
        """
class A:
    pass

def main():
    # !DocumentClass
    gene = A()
        """
    )

    assert classes == []


def test_extract_annotations():
    classes = extract_from_str(
        """
from biolink_model.datamodel.pydanticmodel_v2 import Gene

def main():
    # !DocumentClass
    gene = Gene(
        # note: this is a note
        # source: this is the source
        # value: this is about the value
        label="label"
    )
        """
    )

    assert classes[0].fields[0].annotations.note == "this is a note"
    assert classes[0].fields[0].annotations.source == "this is the source"
    assert classes[0].fields[0].annotations.value == "this is about the value"


def test_extract_multiline_annotations():
    classes = extract_from_str(
        """
from biolink_model.datamodel.pydanticmodel_v2 import Gene

def main():
    # !DocumentClass
    gene = Gene(
        # note: this is a note
        # that spans multiple lines
        label="label"
    )
        """
    )

    assert classes[0].fields[0].annotations.note == "this is a note that spans multiple lines"


def test_infer_source():
    classes = extract_from_str(
        """
from biolink_model.datamodel.pydanticmodel_v2 import Gene

def main():
    # !DocumentClass
    gene = Gene(
        label=row["label"]
    )
        """
    )

    assert classes[0].fields[0].parsed_source == ["label"]


def test_infer_constant():
    classes = extract_from_str(
        """
from biolink_model.datamodel.pydanticmodel_v2 import Gene

def main():
    # !DocumentClass
    gene = Gene(
        label="label"
    )
        """
    )

    assert classes[0].fields[0].constant == "label"


def test_infer_source_from_variable():
    classes = extract_from_str(
        """
from biolink_model.datamodel.pydanticmodel_v2 import Gene

def main(row):
    a = row["label"]

    # !DocumentClass
    gene = Gene(
        label=a
    )
        """
    )

    assert classes[0].fields[0].parsed_source == ["label"]


def test_infer_multiple_sources():
    classes = extract_from_str(
        """
from biolink_model.datamodel.pydanticmodel_v2 import Gene

def main():
    # !DocumentClass
    gene = Gene(
        label=row["label"] or row["identifier"]
    )
        """
    )

    assert classes[0].fields[0].parsed_source == ["label", "identifier"]
