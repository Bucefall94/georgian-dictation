from georgian_dictation.services.diagnostics import normalize_words, word_error_rate


def test_georgian_normalization() -> None:
    assert normalize_words("გამარჯობა, თბილისი!") == ["გამარჯობა", "თბილისი"]


def test_wer() -> None:
    assert word_error_rate("ერთი ორი სამი", "ერთი სამი") == 1 / 3
    assert word_error_rate("ერთი ორი", "ერთი ოთხი") == 1 / 2
    assert word_error_rate("", "ტექსტი") is None

