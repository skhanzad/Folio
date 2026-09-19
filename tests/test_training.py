from scripts.train_openreview import eligible_records, label_for


def test_ground_truth_requires_explicit_final_decisions():
    assert label_for("Accept (Poster)") == 1
    assert label_for("Accept (Oral)") == 1
    assert label_for("Reject") == 0
    for ambiguous in (
        "Withdrawn (treated as Reject)",
        "Withdraw",
        "Desk Reject",
        "Conditional Poster",
        "",
        "Accept?",
    ):
        assert label_for(ambiguous) is None


def test_sampling_excludes_disagreement_withdrawals_and_duplicate_manuscripts():
    notes, corroboration, pdfs = [], [], []
    for forum, decision, status, title in (
        ("a", "Accept (Poster)", "Poster", "Accepted paper"),
        ("b", "Reject", "Reject", "Rejected paper"),
        ("c", "Reject", "Poster", "Disputed paper"),
        ("d", "Withdrawn (treated as Reject)", "Withdraw", "Withdrawn paper"),
        ("e", "Accept (Poster)", "Poster", "Accepted paper!"),
        ("f", "Reject", "Desk Reject", "Desk rejection"),
    ):
        notes.append(
            {
                "paper_id": forum,
                "decision": decision,
                "title": title,
                "pdf_url": "https://openreview.net/pdf?id=" + forum,
            }
        )
        corroboration.append({"id": forum, "status": status})
        pdfs.append({"path": "pdfs/" + forum + ".pdf", "size": 100, "lfs": {"oid": "a" * 64}})
    rows, exclusions = eligible_records(notes, corroboration, pdfs)
    assert [(r["forum_id"], r["label"]) for r in rows] == [("a", 1), ("b", 0)]
    assert exclusions == {"nonfinal_or_disputed_decision": 3, "duplicate_title": 1}
