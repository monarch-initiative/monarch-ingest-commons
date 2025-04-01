import pytest

from monarch_ingest_commons.transform_koza import transform_koza_code


@pytest.mark.parametrize(
    "test_input,expected",
    [
        (
            """
# A comment
while (row := koza_app.get_row()) is not None:
    pass
        """,
            """
# A comment
def transform_record(koza: Koza, record: dict[str, Any]):
    pass
        """,
        ),
        (
            "label = row['Name']",
            "label = record['Name']",
        ),
        (
            """
from koza.cli_utils import get_koza_app

koza_app = get_koza_app("transform_name")

print("ok")
            """,
            """

print("ok")
            """,
        ),
        (
            "koza_app.write(a, b, c)",
            "koza.write(a, b, c)",
        ),
        (
            """
m = koza_app.get_map("map_name")

x = m["foo"]
y = m[bar]
z = m[a]['b']
a = m.get("z")
            """,
            """

x = koza.lookup("foo", "map_name")
y = koza.lookup(bar, "map_name")
z = koza.lookup(a, "map_name")['b']
a = koza.lookup("z", "map_name")
            """,
        ),
    ],
)
def test_koza_transform(test_input: str, expected: str) -> None:
    result = transform_koza_code(test_input)
    assert result.code == expected
