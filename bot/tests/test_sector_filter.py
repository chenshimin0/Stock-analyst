import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sector_selector import is_main_board, is_st


def test_is_main_board():
    assert is_main_board("600000") is True   # Shanghai main
    assert is_main_board("000001") is True   # Shenzhen main
    assert is_main_board("002415") is True   # Shenzhen SME (now part of main)
    assert is_main_board("300750") is False  # ChiNext
    assert is_main_board("688017") is False  # STAR market
    assert is_main_board("830799") is False  # BSE
    assert is_main_board("400003") is False  # legacy
    assert is_main_board("900901") is False  # B-share


def test_is_st():
    assert is_st("平安银行") is False
    assert is_st("ST华联") is True
    assert is_st("*ST大集") is True
    assert is_st("st国华") is True  # case-insensitive
