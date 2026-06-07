import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sector_selector import is_main_board, is_st, is_within_market_cap, is_within_pe_median


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


def test_is_within_market_cap():
    assert is_within_market_cap(450.0) is True
    assert is_within_market_cap(500.0) is True  # boundary
    assert is_within_market_cap(500.01) is False
    assert is_within_market_cap(0) is False
    assert is_within_market_cap(-10) is False


def test_is_within_pe_median():
    pe_list = [10, 20, 30, 40, 50, 60, 70]
    median = 40
    assert is_within_pe_median(20, median) is True   # below median
    assert is_within_pe_median(40, median) is False  # at median
    assert is_within_pe_median(0, median) is False   # no data
    assert is_within_pe_median(-5, median) is False  # negative (loss)
