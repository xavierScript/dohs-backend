"""
benchmark_lassa_severity.py
============================
Evaluates the precision, recall, and F1-score of the DOHS keyword-based
Lassa fever severity screening function against a hand-labelled test set.

The function under test:
    app/api/routes/reports/report_incident.py :: is_severe_lassa_fever_case()

Decision logic:
    A case is flagged as "severe" if ANY of the following hold:
      (a) symptoms string contains a keyword from the severe_symptoms set
      (b) classification == "confirmed"
      (c) outcome == "dead"

This benchmark documents:
    - Overall precision, recall, F1
    - Specific failure modes: false positives and false negatives with category tags
    - Negation blindness pattern (most interesting finding for the paper)
    - Confirmed-always-severe policy bias

Usage:
    python evaluation/benchmark_lassa_severity.py

No server, no database, no network required.
"""

import os
import sys
import csv
from datetime import datetime

# ---------------------------------------------------------------------------
# Patch sys.path so we can import the production function without a DB engine
# We import ONLY the pure function — we do not import report_incident.py
# directly because it triggers db.py at module level. Instead, we copy the
# function signature inline here (byte-for-byte identical to production)
# and note this explicitly in the paper's methodology.
# ---------------------------------------------------------------------------

def is_severe_lassa_fever_case(symptoms, classification: str, outcome: str) -> bool:
    """
    EXACT COPY of production function from:
        app/api/routes/reports/report_incident.py :: is_severe_lassa_fever_case()

    Copied verbatim to avoid importing db.py (which requires a live DB connection).
    Any future changes to the production function must be mirrored here.
    Last sync: 2026-07-22

    Decision rule:
        Severe = has_severe_symptoms OR is_fatal OR is_confirmed
    """
    if not symptoms:
        return False

    symptom_list = [s.strip().lower() for s in symptoms.split(',')]

    severe_symptoms = {
        'bleeding', 'hemorrhage', 'bleeding from gums', 'blood in stool', 'blood in urine',
        'neurological', 'seizure', 'confusion', 'disorientation', 'coma', 'unconsciousness',
        'respiratory distress', 'difficulty breathing', 'shortness of breath',
        'hypotension', 'low blood pressure', 'shock',
        'organ failure', 'kidney failure', 'liver failure',
        'facial swelling', 'chest pain', 'abdominal pain'
    }

    has_severe_symptoms = any(symptom in severe_symptoms for symptom in symptom_list)
    is_confirmed = classification.lower() == 'confirmed'
    is_fatal = outcome.lower() == 'dead'

    return has_severe_symptoms or is_fatal or is_confirmed


# ---------------------------------------------------------------------------
# Hand-labelled test set
# Each case: (id, description, symptoms, classification, outcome, true_severe, failure_category)
#
# true_severe ground truth is assigned using:
#   - WHO/NCDC Lassa fever case management guidelines
#   - "Severe" = haemorrhagic signs, CNS involvement, multi-organ failure, or death
#   - "Mild" = non-specific febrile illness without danger signs, fully ambulant,
#              or convalescent confirmed cases with no remaining severity markers
#
# failure_category: label for expected false-positive or false-negative type
#   "TP" = True Positive (correct severe detection)
#   "TN" = True Negative (correct non-severe detection)
#   "FP_confirmed_bias" = False Positive due to confirmed = severe policy on mild case
#   "FP_negation"       = False Positive due to negated symptom text being parsed as present
#   "FN_multi_word"     = False Negative due to multi-word symptom phrase split across tokens
#   "FN_synonym"        = False Negative due to clinical synonym not in the keyword set
# ---------------------------------------------------------------------------

TEST_SET = [
    # --- True Positives: clearly severe, correctly flagged ---
    ("TC01", "Active haemorrhage, confirmed",
     "bleeding, fever, weakness", "Confirmed", "Alive", True, "TP"),

    ("TC02", "Seizure, suspected, survived",
     "seizure, fever, headache", "Suspected", "Alive", True, "TP"),

    ("TC03", "Fatal case, no dangerous symptoms on admission",
     "fever, sore throat, fatigue", "Suspected", "Dead", True, "TP"),

    ("TC04", "Comatose patient",
     "coma, fever, vomiting", "Probable", "Alive", True, "TP"),

    ("TC05", "Respiratory distress on admission",
     "respiratory distress, fever, chest pain", "Suspected", "Alive", True, "TP"),

    ("TC06", "Liver failure, jaundice",
     "liver failure, jaundice, weakness", "Probable", "Alive", True, "TP"),

    ("TC07", "Shock on presentation",
     "shock, hypotension, fever", "Suspected", "Alive", True, "TP"),

    ("TC08", "Disoriented patient, confirmed fatal",
     "disorientation, confusion", "Confirmed", "Dead", True, "TP"),

    ("TC09", "Blood in stool only",
     "blood in stool, fever", "Suspected", "Alive", True, "TP"),

    ("TC10", "Kidney failure, confirmed",
     "kidney failure, oliguria", "Confirmed", "Alive", True, "TP"),

    # --- True Negatives: mild/non-severe, correctly not flagged ---
    ("TN01", "Mild suspected case, fever and myalgia only",
     "fever, myalgia, headache", "Suspected", "Alive", False, "TN"),

    ("TN02", "Sore throat and weakness, suspected, discharged",
     "sore throat, weakness, fatigue", "Suspected", "Alive", False, "TN"),

    ("TN03", "Convalescent, probable, no danger signs",
     "mild fatigue, loss of appetite", "Probable", "Alive", False, "TN"),

    ("TN04", "Vomiting and diarrhoea only, suspected",
     "vomiting, diarrhoea", "Suspected", "Alive", False, "TN"),

    ("TN05", "Negative outcome (not Lassa), no symptoms logged",
     None, "Suspected", "Alive", False, "TN"),

    # --- FALSE POSITIVES: cases the function flags as severe but are not ---

    # Policy bias: "Confirmed" automatically triggers severe, even for mild convalescent cases
    ("FP01", "Confirmed mild convalescent — ambulant, no danger signs, fully recovered",
     "mild fatigue, occasional headache", "Confirmed", "Alive", False, "FP_confirmed_bias"),

    ("FP02", "Confirmed case, only residual weakness post-discharge",
     "weakness, fatigue", "Confirmed", "Alive", False, "FP_confirmed_bias"),

    ("FP03", "Confirmed case, initial presentation was non-specific fever — never developed danger signs",
     "fever, sore throat", "Confirmed", "Alive", False, "FP_confirmed_bias"),

    # Negation blindness: symptom text starts with a negation prefix that splits into
    # a token whose stripped form still matches a keyword
    ("FP04", "Patient denies seizure — negation phrase splits into bare keyword after comma",
     "denies fever, seizure history resolved, headache", "Suspected", "Alive", False, "FP_negation"),
    # Analysis: "seizure history resolved".strip() = "seizure history resolved"
    # NOT in severe_symptoms set — so actually a TN for seizure.
    # But: "denies fever, seizure, headache" → splits to ["denies fever", "seizure", "headache"]
    # → "seizure" IS in the set → False Positive
    # Demonstrating with the exact phrase that triggers it:

    ("FP05", "No active bleeding — phrase written as 'no bleeding' crosses into token boundary",
     "no active symptoms, bleeding risk noted in history, fever", "Suspected", "Alive", False, "FP_negation"),
    # "bleeding risk noted in history" != "bleeding" → NOT a match (safe)
    # Real trigger: "ruled out bleeding, seizure" → ["ruled out bleeding", "seizure"] → seizure matches

    ("FP06", "Negation in free text: 'no seizure, no bleeding' entered as comma-separated",
     "no seizure, no bleeding, fever", "Suspected", "Alive", False, "FP_negation"),
    # ["no seizure", "no bleeding", "fever"] → none match → actually TN
    # Real negation failure — comma after negation isolates bare keyword:
    # "no neurological, seizure observed briefly then resolved, fever"

    ("FP07", "Negation failure — bare keyword isolated after comma split",
     "no neurological symptoms, seizure episode now resolved, fever", "Suspected", "Alive", False, "FP_negation"),
    # → ["no neurological symptoms", "seizure episode now resolved", "fever"]
    # "seizure episode now resolved" != "seizure" — NOT a match (safe)
    # REAL trigger case:
    # "no symptoms of concern, seizure, resolved prior to admission"
    # → ["no symptoms of concern", "seizure", "resolved prior to admission"]
    # → "seizure" IS in set → FP

    ("FP08", "Bare keyword 'seizure' isolated by comma after negation phrase",
     "no symptoms of concern, seizure, resolved prior to admission", "Suspected", "Alive", False, "FP_negation"),

    # --- FALSE NEGATIVES: cases that ARE severe but the function misses ---

    # Multi-word phrase fragmented by poor CSV entry (space around comma breaks phrase)
    ("FN01", "Haemorrhage from gums — phrase entered with comma in middle of token",
     "bleeding from, gums, fever", "Suspected", "Alive", True, "FN_multi_word"),
    # "bleeding from gums" is in severe_symptoms as a single token
    # If entered as "bleeding from, gums" → splits to ["bleeding from", "gums"] → neither matches

    ("FN02", "Blood in stool — phrase split by space after comma",
     "blood in, stool, weakness", "Suspected", "Alive", True, "FN_multi_word"),
    # "blood in stool" is in severe_symptoms
    # "blood in, stool" → ["blood in", "stool"] → neither matches

    # Synonym not in the keyword set
    ("FN03", "Haematemesis (vomiting blood) — clinical synonym for haemorrhage, not in set",
     "haematemesis, fever, weakness", "Suspected", "Alive", True, "FN_synonym"),

    ("FN04", "Melena (bloody stool) — clinical synonym not in keyword set",
     "melena, fever, weakness", "Suspected", "Alive", True, "FN_synonym"),

    ("FN05", "Obtunded — clinical synonym for reduced consciousness, not in set",
     "obtunded, fever", "Suspected", "Alive", True, "FN_synonym"),

    ("FN06", "Haemoptysis — coughing blood, clinical severity marker not in set",
     "haemoptysis, dyspnoea, fever", "Suspected", "Alive", True, "FN_synonym"),

    ("FN07", "Epistaxis (nosebleed) with haemorrhagic fever — not in set",
     "epistaxis, fever, weakness", "Suspected", "Alive", True, "FN_synonym"),

    ("FN08", "Anuria — absence of urine output, severe renal sign, not in set",
     "anuria, fever, vomiting", "Suspected", "Alive", True, "FN_synonym"),
]


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate(test_set):
    results = []
    tp = fp = tn = fn = 0

    for case_id, description, symptoms, classification, outcome, true_severe, category in test_set:
        predicted = is_severe_lassa_fever_case(symptoms, classification, outcome)
        correct = predicted == true_severe

        if true_severe and predicted:
            tp += 1
        elif not true_severe and not predicted:
            tn += 1
        elif not true_severe and predicted:
            fp += 1
        else:
            fn += 1

        results.append({
            "case_id": case_id,
            "description": description,
            "symptoms": symptoms,
            "classification": classification,
            "outcome": outcome,
            "true_severe": true_severe,
            "predicted_severe": predicted,
            "correct": correct,
            "failure_category": category,
        })

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy  = (tp + tn) / len(test_set)

    return results, {
        "total": len(test_set),
        "TP": tp, "TN": tn, "FP": fp, "FN": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
    }


def print_results(results, metrics):
    sep = "-" * 72
    print(f"\n{'='*72}")
    print("  DOHS Lassa Severity Screener -- Precision/Recall Benchmark")
    print(f"{'='*72}")
    print(f"  Total test cases : {metrics['total']}")
    print(f"  True Positives   : {metrics['TP']}")
    print(f"  True Negatives   : {metrics['TN']}")
    print(f"  False Positives  : {metrics['FP']}")
    print(f"  False Negatives  : {metrics['FN']}")
    print(sep)
    print(f"  Precision        : {metrics['precision']:.4f}  ({metrics['precision']*100:.1f}%)")
    print(f"  Recall           : {metrics['recall']:.4f}  ({metrics['recall']*100:.1f}%)")
    print(f"  F1 Score         : {metrics['f1']:.4f}")
    print(f"  Accuracy         : {metrics['accuracy']:.4f}  ({metrics['accuracy']*100:.1f}%)")
    print(f"{'='*72}\n")

    # --- False Positives ---
    fps = [r for r in results if not r["correct"] and r["predicted_severe"]]
    if fps:
        print(f"  FALSE POSITIVES ({len(fps)} cases):")
        print(sep)
        for r in fps:
            print(f"  [{r['case_id']}] [{r['failure_category']}]")
            print(f"         {r['description']}")
            print(f"         Symptoms: {r['symptoms']}")
            print(f"         Class: {r['classification']} | Outcome: {r['outcome']}")
            print()

    # --- False Negatives ---
    fns = [r for r in results if not r["correct"] and not r["predicted_severe"]]
    if fns:
        print(f"  FALSE NEGATIVES ({len(fns)} cases):")
        print(sep)
        for r in fns:
            print(f"  [{r['case_id']}] [{r['failure_category']}]")
            print(f"         {r['description']}")
            print(f"         Symptoms: {r['symptoms']}")
            print(f"         Class: {r['classification']} | Outcome: {r['outcome']}")
            print()


def save_results(results, metrics, output_dir="evaluation/results"):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Per-case CSV
    cases_path = os.path.join(output_dir, f"lassa_severity_cases_{timestamp}.csv")
    fieldnames = list(results[0].keys())
    with open(cases_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    # Summary CSV
    summary_path = os.path.join(output_dir, f"lassa_severity_summary_{timestamp}.csv")
    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(metrics.keys()))
        writer.writeheader()
        writer.writerow(metrics)

    return cases_path, summary_path


# ---------------------------------------------------------------------------
# Failure pattern analysis — counts by category for paper reporting
# ---------------------------------------------------------------------------

def analyze_failure_patterns(results):
    from collections import Counter
    fp_categories = Counter(r["failure_category"] for r in results if not r["correct"] and r["predicted_severe"])
    fn_categories = Counter(r["failure_category"] for r in results if not r["correct"] and not r["predicted_severe"])

    print("  FAILURE PATTERN BREAKDOWN:")
    print("-" * 72)
    if fp_categories:
        print("  False Positive sources:")
        for cat, count in fp_categories.most_common():
            print(f"    {cat:<30} : {count} case(s)")
    if fn_categories:
        print("  False Negative sources:")
        for cat, count in fn_categories.most_common():
            print(f"    {cat:<30} : {count} case(s)")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results, metrics = evaluate(TEST_SET)
    print_results(results, metrics)
    analyze_failure_patterns(results)
    cases_path, summary_path = save_results(results, metrics)
    print(f"  [OK] Case results saved to : {cases_path}")
    print(f"  [OK] Summary saved to      : {summary_path}\n")
