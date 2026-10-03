"""Captions stay right to left even when a line opens with a masked word."""

from __future__ import annotations

from doxa.publish import RLM, normalize_caption, rtl_caption


def test_line_opening_with_latin_masked_word_gets_rlm():
    text = "Zונות זה לא תירוץ.\nשמור את הפוסט.\n.\n#גרושים #סילברפוקס"
    out = rtl_caption(text).split("\n")
    assert out[0] == RLM + "Zונות זה לא תירוץ."
    assert out[1:] == ["שמור את הפוסט.", ".", "#גרושים #סילברפוקס"]


def test_hebrew_first_lines_and_masks_inside_are_untouched():
    text = "הוא חושב עם הZין.\nSex\n.\n"
    assert rtl_caption(text) == text  # Hebrew first; an all Latin line stays as is


def test_recovery_matches_the_sent_caption():
    text = "Kוסית לא תציל אותך.\n#גרושים"
    assert normalize_caption(rtl_caption(text)) == normalize_caption(text)
