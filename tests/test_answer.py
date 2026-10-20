from mtl_analyst.answer import Answer, split_sentences, verify
from mtl_analyst.tools import StoredResult

R1 = StoredResult(
    "R1", "q", "q", ["borough", "trips"], [["Le Plateau-Mont-Royal", 4643362], ["Ville-Marie", 3521715]], False
)
R2 = StoredResult("R2", "q", "q", ["share"], [[0.3271]], False)


def test_numbers_present_in_cited_result_are_kept():
    verdict = verify(
        Answer(text="The Plateau had 4,643,362 trips [R1]. Ville-Marie had 3 521 715 [R1].", result_ids=["R1"]),
        [R1, R2],
    )

    assert verdict.passed
    assert len(verdict.kept) == 2


def test_a_number_not_in_the_cited_result_is_dropped_with_a_reason():
    verdict = verify(
        Answer(
            text="The Plateau had 4,643,362 trips [R1]. That is 5,000,000 more than last year [R1].", result_ids=["R1"]
        ),
        [R1],
    )

    assert [s.text for s in verdict.kept] == ["The Plateau had 4,643,362 trips [R1]."]
    assert verdict.dropped[0][1] == "5000000 not in cited result(s) R1"


def test_numbers_without_any_citation_are_dropped():
    verdict = verify(Answer(text="There were 14 million trips.", result_ids=[]), [R1])

    assert not verdict.passed
    assert "cites no result" in verdict.dropped[0][1]


def test_percentages_match_fractions_in_the_result():
    verdict = verify(Answer(text="The Plateau's share was 32.7% [R2].", result_ids=["R2"]), [R2])

    assert verdict.passed


def test_the_data_year_and_question_numbers_are_free():
    verdict = verify(
        Answer(text="In 2025 the top 5 boroughs were as follows [R1].", result_ids=["R1"]),
        [R1],
        allowed_free_numbers={"5"},
    )

    assert verdict.passed


def test_sentences_split_on_terminal_punctuation_only():
    sentences = split_sentences("Trips rose to 4,643,362 [R1]. Median was 12.5 min [R2].")

    assert [s.result_ids for s in sentences] == [("R1",), ("R2",)]
    assert sentences[1].numbers == ("12.5",)


def test_numbers_the_model_wrote_into_the_cited_sql_are_free():
    limited = StoredResult(
        "R3", "select station from stations order by departures_2025 desc limit 10", "", ["station"], [["A"]], False
    )
    verdict = verify(Answer(text="The top 10 stations are listed [R3].", result_ids=["R3"]), [limited])

    assert verdict.passed
