from src.collectors.who_collector import WHOCollector


def test_who_keyword_matching_uses_complete_terms():
    assert WHOCollector.keyword_matches("In-prison vaccination for seasonal flu", "seasonal flu")
    assert WHOCollector.keyword_matches("HIV tests performed", "hiv")
    assert WHOCollector.keyword_matches("TB treatment coverage", "tb")
    assert not WHOCollector.keyword_matches("Magnetic flux density", "flu")
    assert not WHOCollector.keyword_matches("Fluoride toothpaste", "flu")
    assert not WHOCollector.keyword_matches("SA_0000001398_ARCHIVED", "hiv")
