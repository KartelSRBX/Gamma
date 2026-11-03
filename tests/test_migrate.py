from gamma.migrate import split_statements


def test_statements_are_split_on_semicolons():
    assert split_statements(
        "CREATE TABLE a (x UInt8) ENGINE = Memory;\nCREATE TABLE b (y UInt8) ENGINE = Memory;"
    ) == [
        "CREATE TABLE a (x UInt8) ENGINE = Memory",
        "CREATE TABLE b (y UInt8) ENGINE = Memory",
    ]


def test_a_semicolon_in_a_comment_does_not_split():
    sql = "-- first; second\nCREATE TABLE a (x UInt8) ENGINE = Memory; -- trailing; note\n"
    assert split_statements(sql) == ["CREATE TABLE a (x UInt8) ENGINE = Memory"]
