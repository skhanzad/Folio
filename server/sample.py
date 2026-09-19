"""Original synthetic manuscript used for demonstrations and controlled checks."""

import pymupdf

SAMPLE_SECTIONS = [
    (
        "Abstract",
        "We study whether explicit uncertainty reporting improves the interpretability of a small document-classification system. In this synthetic demonstration, a logistic regression baseline is compared with temperature-scaled predictions on a fixed, balanced collection of 600 generated abstracts. We report held-out accuracy and calibration error over five random seeds. Calibration improves while accuracy is unchanged within sampling variation. These illustrative results describe a controlled toy setting; they do not establish performance on real scholarly documents.",
    ),
    (
        "1 Introduction",
        "Automated document triage often exposes a class label without the uncertainty behind it. Readers may mistake a confident prediction for a reliable one. Our research question is whether a simple post-processing calibration step can improve the match between prediction confidence and observed accuracy without changing the classifier. The contribution is a small, reproducible evaluation protocol separating training, calibration, and testing. This original synthetic manuscript is a software demonstration and is not a published scientific study.",
    ),
    (
        "2 Related Work",
        "Proper scoring rules formalize evaluation of probabilistic predictions [1]. Calibration methods adjust confidence estimates while preserving a predictor's ranking, with temperature scaling providing a simple example [2]. Our protocol uses these established ideas rather than claiming a new calibration algorithm. A broader comparison with isotonic regression would help establish whether the chosen baseline is appropriate; that comparison is left for future work.",
    ),
    (
        "3 Methods",
        "We construct 600 synthetic abstracts balanced across three topic classes. A fixed stratified split allocates 360 abstracts to training, 120 to calibration, and 120 to testing. A TF-IDF representation with unigrams and bigrams feeds a multinomial logistic regression with L2 regularization and C=1. Vocabulary construction uses training data only. Temperature is selected on the calibration split by minimizing negative log likelihood. The held-out test split is never used for model or temperature selection. We repeat the procedure for random seeds 11, 23, 37, 41, and 59. Expected calibration error uses ten equal-width confidence bins. We report means and standard deviations across seeds. Generated templates are separated between splits to reduce template leakage. This procedure can assess the toy data distribution only.",
    ),
    (
        "4 Results",
        "In this synthetic example, the baseline achieves 81.2% accuracy with a standard deviation of 1.8 percentage points across seeds. Temperature scaling achieves the same accuracy, as expected because it preserves the maximal-logit class. Mean expected calibration error decreases from 0.142 to 0.061; standard deviations are 0.024 and 0.018 respectively. These numbers are illustrative fixture values, not outputs of a conducted experiment. No statistical significance or real-world improvement is claimed. A seed-level result table and confidence intervals would be needed for a publishable empirical evaluation.",
    ),
    (
        "5 Discussion and Limitations",
        "The protocol illustrates why discrimination and calibration should be reported separately. The apparent calibration benefit applies only to the constructed distribution and should not be generalized to natural abstracts. Generated text can encode label shortcuts, a small test split makes bin-based calibration estimates unstable, and the experiment does not test distribution shift. The absence of executed experiments is a central limitation of this demonstration. Future work should use independently annotated documents, report inter-annotator agreement, compare multiple calibration approaches, and inspect failure cases before making practical recommendations.",
    ),
    (
        "6 Conclusion",
        "We describe a transparent protocol for separating classifier accuracy from calibration quality. The synthetic values make the interface easy to inspect but supply no empirical evidence for deployment. A substantive contribution would require execution of the protocol on real documents, external replication, and careful analysis of uncertainty. Explicit scope and limitations are essential when presenting model-based assessments.",
    ),
    (
        "References",
        "[1] Gneiting, T. and Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. Journal of the American Statistical Association, 102(477), 359-378.\n[2] Guo, C., Pleiss, G., Sun, Y., and Weinberger, K. Q. (2017). On Calibration of Modern Neural Networks. Proceedings of ICML, PMLR 70, 1321-1330.",
    ),
]


def sample_pdf(weak: bool = False) -> bytes:
    doc = pymupdf.open()
    title = "Uncertainty-aware document classification"
    doc.set_metadata({"title": title, "author": "Folio synthetic example"})
    page = doc.new_page(width=595, height=842)
    if (
        page.insert_textbox(
            pymupdf.Rect(54, 48, 541, 132), title, fontsize=24, fontname="hebo", color=(0.16, 0.21, 0.18)
        )
        < 0
    ):
        raise RuntimeError("Sample title did not fit.")
    page.insert_text((54, 137), "FOLIO RESEARCH NOTES  /  SYNTHETIC EXAMPLE", fontsize=9, fontname="helv")
    y = 172
    for heading, text in SAMPLE_SECTIONS:
        if weak and heading not in ("References", "Abstract"):
            text = "Our system is the best. We did some tests and they worked. The method is obvious and no further details are needed. Everyone should use it. We do not provide data, comparisons, or uncertainty estimates. We assume our claims are universally true."
        required = 45 + len(text) / 94 * 16
        if y + required > 780:
            page = doc.new_page(width=595, height=842)
            y = 58
        page.insert_text((54, y), heading, fontsize=13, fontname="hebo")
        box = pymupdf.Rect(54, y + 12, 541, y + required)
        spare = page.insert_textbox(box, text, fontsize=10.5, fontname="helv", lineheight=1.45)
        if spare < 0:
            raise RuntimeError("Sample text did not fit its page.")
        y += required + 14
    for i, page in enumerate(doc):
        page.insert_text(
            (54, 814),
            f"Folio / illustrative manuscript                                      {i + 1}",
            fontsize=8,
            color=(0.45, 0.45, 0.45),
        )
    result = doc.tobytes()
    doc.close()
    return result
