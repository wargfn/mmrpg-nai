from mmrpg_nai.cli.main import _mask_token


def test_mask_token_empty() -> None:
    assert _mask_token("") == "(empty)"


def test_mask_token_short() -> None:
    assert _mask_token("abcd") == "****"


def test_mask_token_medium() -> None:
    assert _mask_token("abcde1234") == "ab*****34"


def test_mask_token_long() -> None:
    assert _mask_token("ghp_1234567890abcd") == "ghp_**********abcd"
