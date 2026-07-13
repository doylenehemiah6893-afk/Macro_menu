from catvba_refactor.macro_build.canonical import canonical_json_bytes, sha256_bytes


def test_canonical_json_is_key_order_independent() -> None:
    left = canonical_json_bytes({"b": 2, "a": "中"})
    right = canonical_json_bytes({"a": "中", "b": 2})
    assert left == right == b'{"a":"\\u4e2d","b":2}\n'
    assert sha256_bytes(left) == sha256_bytes(right)
