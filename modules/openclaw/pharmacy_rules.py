"""
Deterministic behaviour rules for the Platinum Pharmacy WhatsApp bot.

Everything here is a pure function (no DB, no network) so the same rules can be
applied in the chat flow AND covered by scenario tests:

1. Phone numbers must be valid 10-digit local numbers (0771234567 / +263771234567)
2. Prices are always shown rounded to the nearest whole number
3. Only products that are active AND in stock are offered
4. Misspellings are corrected / suggested ("nivia" -> Nivea, "benylin 4 flu" ~ "benylin for flu")
5. An unsure customer is never *suggested* medication - the request is handed to
   the pharmacist; a sure customer is asked to double-check before ordering
"""

import math
import re
import difflib
from typing import Dict, List, Optional, Tuple


# ===========================================================================
# 1. PHONE NUMBER VALIDATION (exactly 10 digits)
# ===========================================================================

PHONE_EXAMPLE = "0771234567"

PHONE_ERROR_MESSAGE = (
    "Please send a valid *10-digit* phone number, e.g. "
    f"{PHONE_EXAMPLE} (or +263771234567).\n\n"
    "_Tip: say 'cart' to view your cart, or 'cancel' to go back._"
)


def normalize_phone(raw) -> Tuple[Optional[str], Optional[str]]:
    """Normalise a phone number and validate it as a 10-digit local number.

    Accepts "077 123 4567", "077-123-4567", "+263771234567", "263771234567"
    and "00263771234567".

    Returns (normalized, None) on success - e.g. ("0771234567", None) - or
    (None, error_message) when the number is not a valid 10-digit number.
    """
    if raw is None:
        return None, PHONE_ERROR_MESSAGE

    cleaned = str(raw).strip().lower()
    cleaned = cleaned.replace("tel:", "").replace("whatsapp:", "")
    cleaned = re.sub(r"[\s\-().,]", "", cleaned)
    cleaned = cleaned.lstrip("intl:")

    # 00263 / +263 / 263 -> local 0-prefix form
    m = re.match(r"^(?:\+|00)?263(\d{7,10})$", cleaned)
    if m:
        cleaned = "0" + m.group(1)

    if not cleaned.isdigit():
        return None, PHONE_ERROR_MESSAGE
    if len(cleaned) != 10:
        return None, PHONE_ERROR_MESSAGE
    if not cleaned.startswith("0"):
        return None, PHONE_ERROR_MESSAGE

    return cleaned, None


def extract_phone(text) -> Tuple[Optional[str], Optional[str]]:
    """Pull the first valid 10-digit phone number out of a free-text message.

    Returns (normalized, None) when one is found, else (None, error_message).
    """
    if not text:
        return None, PHONE_ERROR_MESSAGE
    for candidate in re.findall(r"(?:\+|00)?263\d{7,10}|0\d{9}|\d{10}", str(text)):
        normalized, err = normalize_phone(candidate)
        if normalized:
            return normalized, None
    return None, PHONE_ERROR_MESSAGE


def is_valid_phone(raw) -> bool:
    """True when `raw` normalises to a valid 10-digit number."""
    return normalize_phone(raw)[0] is not None


# ===========================================================================
# 2. WHOLE-NUMBER PRICE ROUNDING
# ===========================================================================

def round_price(value) -> int:
    """Round a price to the nearest whole number (0.5 rounds up)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0
    if math.isnan(number) or math.isinf(number):
        return 0
    return int(math.floor(number + 0.5)) if number >= 0 else -int(math.floor(-number + 0.5))


def parse_price(text) -> Optional[float]:
    """Parse "$6.00" / "6.00 USD" / 6.0 into a float. None if unparseable."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(text).replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def format_price(value) -> str:
    """Whole-dollar price string, e.g. format_price(9.75) -> '$10'."""
    return f"${round_price(value)}"


def cart_subtotal(items: Optional[List[Dict]]) -> int:
    """Whole-dollar cart subtotal (each line rounded, then x quantity)."""
    total = 0
    for item in items or []:
        line = round_price((item or {}).get("price", 0)) * int((item or {}).get("quantity", 1) or 1)
        total += line
    return total


# ===========================================================================
# 3. ACTIVE / IN-STOCK CHECKING
# ===========================================================================

IN_STOCK = "in_stock"
OUT_OF_STOCK = "out_of_stock"
UNKNOWN_STOCK = "unknown"

_OUT_OF_STOCK_MARKERS = (
    "out of stock", "out-of-stock", "sold out", "soldout", "not in stock",
    "in stock: no", "stock: no", "stock:no", "availability: no",
    "currently unavailable", "discontinued", "temporarily unavailable",
)
_IN_STOCK_MARKERS = ("in stock: yes", "stock: yes", "in stock", "available: yes")


def parse_stock(content: str, product_status: Optional[str] = None,
                sell_when_out_of_stock: Optional[bool] = None) -> str:
    """Read stock state out of a knowledge entry / product row.

    Knowledge content may carry lines like "In Stock: No" or "Out of stock".
    Returns IN_STOCK / OUT_OF_STOCK / UNKNOWN_STOCK.
    """
    if product_status is not None:
        status = str(product_status).lower()
        if status in ("inactive", "draft", "archived", "unpublished"):
            return OUT_OF_STOCK
        if status == "active" and sell_when_out_of_stock:
            return IN_STOCK

    text = (content or "").lower()
    for marker in _OUT_OF_STOCK_MARKERS:
        if marker in text:
            return OUT_OF_STOCK
    for marker in _IN_STOCK_MARKERS:
        if marker in text:
            return IN_STOCK
    return UNKNOWN_STOCK


# ===========================================================================
# 4. FUZZY PRODUCT SPELLING / "DID YOU MEAN" SUGGESTIONS
# ===========================================================================

# WhatsApp shorthand -> words ("benylin 4 flu" ~ "benylin for flu")
_SHORTHAND = {
    "4": "for",
    "wif": "with",
    "&": "and",
    "n": "and",
}

_STOPWORDS = {
    "a", "an", "the", "of", "for", "my", "me", "i", "want", "need", "please",
    "you", "have", "got", "any", "some", "and", "with", "in", "on", "to",
    "do", "does", "is", "are", "what", "which", "show", "give", "buy", "order",
}


def normalize_product_text(text: str) -> str:
    """Lowercase, expand shorthand, strip punctuation - for matching only."""
    if not text:
        return ""
    lowered = str(text).lower()
    lowered = lowered.replace("&", " and ")
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    words = [_SHORTHAND.get(w, w) for w in lowered.split()]
    words = [w for w in words if w]
    return " ".join(words)


def product_tokens(text: str) -> List[str]:
    """Meaningful tokens of a product/query string (shorthand expanded)."""
    tokens = normalize_product_text(text).split()
    return [t for t in tokens if t not in _STOPWORDS] or tokens


def _token_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def suggest_product_names(query: str, candidate_names: List[str],
                          limit: int = 3, cutoff: float = 0.6) -> List[Tuple[str, float]]:
    """Rank catalogue names by how close they are to a (mis)typed query.

    Handles dropped/extra characters ("benilyn" -> "Benylin"), word swaps and
    WhatsApp shorthand ("benylin 4 flu" / "benylin for flu" both match
    "Benylin 4 Flu & Chest Congestion Syrup").

    Returns [(name, score)] sorted best-first, only scores >= cutoff.
    """
    query_norm = normalize_product_text(query)
    query_tokens = product_tokens(query)
    if not query_norm or not candidate_names:
        return []
    # Only short product-like queries get suggestions. Running this on a whole
    # sentence produced gems like "sores on my throat" -> "Benzoyl" and
    # "can i have hiv test kit from angwa" -> "Fluphenazine".
    if len(query_tokens) > 4:
        return []

    ranked = []
    for name in candidate_names:
        name_norm = normalize_product_text(name)
        if not name_norm:
            continue
        if query_norm in name_norm or name_norm in query_norm:
            ranked.append((name, 0.99))
            continue

        overall = _token_similarity(query_norm, name_norm)
        name_tokens = product_tokens(name)

        def _best_for(token: str) -> float:
            best = max([_token_similarity(token, t) for t in name_tokens], default=0.0)
            # Also accept word-boundary containment (e.g. "lotion" in "lotions").
            # A catalogue word buried inside a longer query word only counts when
            # it is most of that word: without the length check "zzzznothing"
            # contained "thin" and was suggested to customers as ALWAYS pads.
            if best < 1.0:
                for word in name_tokens:
                    if len(word) <= 3:
                        continue
                    if token in word or (word in token and len(word) / max(len(token), 1) >= 0.6):
                        best = max(best, 0.9)
            return best

        # Per-token best match, plus how much of the query those matches cover
        matched = 0.0
        best_token = 0.0
        for token in query_tokens:
            best = _best_for(token)
            matched += best
            best_token = max(best_token, best)
        coverage = (matched / len(query_tokens)) if query_tokens else 0.0

        # The BRAND (first meaningful word) has to be recognised, or the
        # suggestion is an unrelated product that merely shares a category word -
        # "sorbet facial wash" must never come back as "Dove Body Wash".
        brand_ok = bool(query_tokens) and _best_for(query_tokens[0]) >= 0.7
        if not brand_ok and overall < 0.75:
            continue

        # One strong token match (the brand) plus decent coverage is enough,
        # even when the whole-string ratio is diluted by pack size/strength.
        score = max(overall, 0.55 * coverage + 0.45 * best_token)
        if score >= cutoff:
            ranked.append((name, round(score, 3)))

    ranked.sort(key=lambda item: (-item[1], len(item[0])))
    # De-duplicate identical names, keep the best score
    seen, deduped = set(), []
    for name, score in ranked:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((name, score))
    return deduped[:limit]


# ===========================================================================
# 5. UNSURE CUSTOMER -> PHARMACIST HANDOVER / "ARE YOU REALLY SURE?"
# ===========================================================================

SURE_CHECK_MARKER = "are you really sure"

PHARMACIST_REVIEW_MESSAGE = (
    "Thank you for reaching out. *Your request has been received and is under "
    "review by our pharmacist.*\n\n"
    "One of our pharmacists will come back to you shortly with the right "
    "guidance - please do not start or change any medication until they "
    "respond. 🙏"
)

# Customer is NOT sure what they want -> never suggest, hand over
UNCERTAIN_PHRASES = (
    "not sure", "im not sure", "am not sure", "don't know", "dont know",
    "not certain", "can't decide", "cant decide", "cannot decide",
    "any suggestion", "any suggestions", "what do you suggest",
    "what do you recommend", "what would you recommend",
    "any recommendation", "any recommendations", "which one is best",
    "which one is better", "what should i take", "what can i take",
    "what do you have for", "help me choose", "help me decide",
    "i have a problem", "i have an issue", "i have symptoms",
    "what works for", "something for my", "not too sure", "unsure",
)

# Words that make a message about medication / prescriptions / health
MEDICATION_WORDS = (
    "medication", "medicine", "medicines", "meds", "tablet", "tablets",
    "capsule", "capsules", "syrup", "pill", "pills", "drug", "drugs",
    "prescription", "rx", "refill", "antibiotic", "dose", "dosage",
    "panadol", "paracetamol", "ibuprofen", "aspirin", "amoxicillin",
    "benylin", "actifed", "flagyl", "augmentin", "coartem", "artemether",
    "omeprazole", "cetirizine", "loratadine", "tramadol", "insulin",
    "metformin", "amlodipine", "losartan", "cough", "flu", "fever",
    "headache", "migraine", "infection", "allergy", "allergies", "asthma",
    "diabetes", "pressure", "ulcer", "diarrhoea", "diarrhea", "nausea",
    "pain", "rash", "thrush", "uti", "stomach", "sore throat", "congestion",
)

# Purchase intent - the customer wants the item, not just information
PURCHASE_INTENT = (
    "i want", "i'd like", "id like", "i would like", "i need", "give me",
    "can i have", "can i get", "i'll take", "i will take", "i wanna",
    "order", "buy", "purchase", "take", "add to cart", "add it", "add this",
    "add ", "also add", "something for", "get me", "sell me",
)

# Informational - no double-confirmation needed, just answer
INFORMATIONAL_INTENT = (
    "how much", "price", "cost", "do you have", "have you got", "is there",
    "are you", "opening", "hours", "location", "address", "delivery",
    "payment", "tell me", "what is", "what are", "explain",
)

AFFIRMATIVES = (
    "yes", "yeah", "yep", "yes please", "yebo", "sure", "sure thing",
    "correct", "right", "that's right", "thats right", "yes i am",
    "yes i'm sure", "yes im sure", "i am sure", "im sure", "i'm sure",
    "proceed", "continue", "go ahead", "confirm", "ok", "okay", "y",
)

NEGATIVES = (
    "no", "nope", "not really", "no thanks", "no thank you", "nah",
    "i'm not", "im not", "i am not", "cancel", "stop", "never mind",
    "nevermind", "dont", "don't", "nope", "i changed my mind",
)


def _contains_any(text: str, phrases) -> Optional[str]:
    for phrase in phrases:
        if phrase in text:
            return phrase
    return None


def is_uncertain_request(text: str) -> bool:
    """True when the customer clearly does not know what they want."""
    if not text:
        return False
    return _contains_any(text.lower(), UNCERTAIN_PHRASES) is not None


def is_medication_related(text: str) -> bool:
    """True when the message is about medication, prescriptions or symptoms."""
    if not text:
        return False
    lowered = text.lower()
    return _contains_any(lowered, MEDICATION_WORDS) is not None


# ---------------------------------------------------------------------------
# Medication / prescription QUESTIONS - answered by a pharmacist, never the bot
# ---------------------------------------------------------------------------
#
# The rule the business runs on: no clinical answer ever comes from the bot.
# Dosage, safety, interactions, pregnancy/child use, side effects, overdose,
# diagnosis-by-symptom and prescriptions are all pharmacist work, so they are
# detected here, deterministically, before any model call happens.

PHARMACIST_QUESTION_MESSAGE = (
    "Our pharmacist is reviewing your question and will reply here shortly.\n\n"
    "I'm the shop assistant, so I'll leave advice about medicines, dosages, "
    "prescriptions and side effects to them. Please wait for their advice "
    "before starting, stopping or changing any medication."
)

# Same rule for a store that is not a pharmacy (no pharmacist on the team): the
# bot still never answers, it just doesn't claim a pharmacist it doesn't have.
HEALTH_QUESTION_MESSAGE = (
    "*This one needs a qualified answer.*\n\n"
    "I'm the shop assistant, so I can't advise on medication, health or "
    "prescriptions.\n\n"
    "I've passed your question to our team and a qualified person will reply to "
    "you here shortly. Please don't start, stop or change any medication until "
    "they do. 🙏"
)

# Prescriptions are pharmacist work on their own: the bot never validates,
# interprets, prices or approves one from a text message.
_PRESCRIPTION_RE = re.compile(
    r"\b(?:prescriptions?|prescribed|scripts?|refills?|rx)\b"
    r"|\bdoctor\s+(?:said|told|recommended|gave|wrote|prescribed)\b"
)

# A message carrying any of these is asking for clinical advice, not shopping.
MEDICATION_QUESTION_PHRASES = (
    # dosage / timing
    "dose", "dosage", "how many can i take", "how many should i take",
    "how many do i take", "how many times a day", "how often can i",
    "how often should i", "how much should i take", "how much can i take",
    "how long should i take", "before or after food", "with food",
    "empty stomach", "over the counter",
    # safety / permission
    "is it safe", "is this safe", "is that safe", "safe to take", "safe for",
    "is it ok to take", "is it okay to take", "is it fine to take",
    "is it alright", "can i take", "can i use", "can she take", "can he take",
    "can i give", "should i take", "should i give", "should i stop",
    "am i allowed", "will it work", "does it work", "work for", "works for",
    "work on", "works on",
    # interactions
    "interact", "interaction", "alcohol", "mix with",
    "together with", "along with my", "with my other", "while pregnant",
    "with my medication", "with my tablets", "with my pressure",
    # pregnancy / children
    "pregnant", "breastfeeding", "breast feeding", "nursing", "conceive",
    # symptoms / diagnosis / treatment
    "what should i take", "what can i take", "what do i take",
    "what should i use", "what can i use", "do you recommend", "you recommend",
    "which one is best", "which is better", "which is stronger",
    "what works for", "what helps", "cure", "treat my", "treatment for",
    "get rid of", "diagnose", "is there something for", "something for",
    "help with my", "good for my",
    # harm / reaction
    "side effect", "side effects", "allergic", "allergy to", "reaction to",
    "overdose", "took too much", "missed a dose", "expired", "gone bad",
)

# Wording that is clinical even when no product is named at all - "can i take
# these two together", "can i drink alcohol with this", "is it safe". Every
# entry here only makes sense about a medicine. Matched on whole words, so
# "cure" cannot fire inside "secure".
_SELF_CLINICAL_PHRASES = (
    "dose", "dosage", "side effect", "side effects", "alcohol", "interact",
    "interaction", "allergic", "allergy", "pregnant", "pregnancy",
    "breastfeeding", "breast feeding", "nursing", "overdose", "took too much",
    "missed a dose", "missed my", "expired", "gone bad", "over the counter",
    "can i take", "can i use", "can i stop", "can i give", "can she take",
    "can he take", "should i take", "should i give", "should i stop",
    "am i allowed", "is it safe", "is this safe", "is that safe",
    "safe to take", "safe to give", "safe for", "is it ok to take",
    "is it okay to take", "is this ok for", "is it fine to take",
    "how many can i take", "how many should i take", "how many do i take",
    "how many times a day", "how often can i", "how often should i",
    "how much should i take", "how much can i take", "how long should i take",
    "before or after food", "with food", "empty stomach", "which is stronger",
    "which is better", "which one is best", "which should i take",
    "which one should i", "do you recommend", "you recommend", "stop taking",
    "for kids", "for children", "for a child", "help me sleep",
    "something to help", "what to take",
)

# Advice wording that is clinical only when the message is already about a
# medicine or a symptom ("what works for my cough", never "what works on rust").
_CONTEXT_CLINICAL_PHRASES = (
    "what should i take", "what can i take", "what do i take",
    "what should i use", "what can i use", "what works for", "works for",
    "work for", "works on", "work on", "what helps", "help with my",
    "good for my", "something for", "is there something for",
    "treatment for", "treat my", "treat", "cure", "get rid of", "diagnose",
    "used for", "will it work", "does it work",
)

# "can my daughter take this" is a question about someone else's dose; "can my
# order be delivered" is not.
_FAMILY_USE_RE = re.compile(
    r"\b(?:can|could|should|may|is it ok|is it okay)\s+(?:my|our)\s+\w+\s+"
    r"(?:take|use|have|drink)\b"
)

# "i need my medication", "i've run out of my tablets" - a refill, not a sale.
_MED_REQUEST_PHRASES = (
    "refill", "run out", "ran out", "out of my", "need my",
    "need more of my", "finished my", "finish my", "renew my",
    "continue my", "missed my",
)

# Drug names change faster than any list can follow, so the endings shared by
# most medicines are matched as well (penicillin, amoxicillin, metformin...).
_DRUG_SUFFIX_RE = re.compile(
    r"\b[a-z]{4,}(?:cillin|mycin|cycline|floxacin|thromycin|prazole|azole|"
    r"olol|statin|dipine|sartan|azepam|zolam|profen|tidine|triptan|"
    r"parin|olone|sone|dine|zine)\b"
)

# Words a question about a medicine can open with ("is amoxicillin an
# antibiotic", "does benylin make you sleepy").
_TOPIC_QUESTION_STARTS = (
    "what", "whats", "where", "which", "who", "how", "is", "are", "was",
    "do", "does", "did", "can", "could", "should", "will", "would", "may",
    "why", "am",
)


def _contains_phrase(text: str, phrases) -> Optional[str]:
    """Whole-word phrase match (so "cure" does not fire inside "secure")."""
    for phrase in phrases:
        if re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", text):
            return phrase
    return None


# "for a 2 year old", "for my baby" - a child dose question even when it is
# phrased as a shopping question ("how much panadol for my baby").
_CHILD_DOSAGE_RE = re.compile(
    r"\b(?:for|to|give)\s+(?:my\s+|a\s+|our\s+|the\s+)?"
    r"(?:\d{1,2}\s*(?:year|yr)s?\s*old|baby|child|kid|son|daughter|toddler|"
    r"infant|newborn)\b"
)

# Names of actual products/drugs. When one of these is named the customer is
# shopping for a product, not asking what to take.
DRUG_NAME_WORDS = (
    "panadol", "paracetamol", "ibuprofen", "aspirin", "amoxicillin",
    "benylin", "actifed", "flagyl", "augmentin", "coartem", "artemether",
    "omeprazole", "cetirizine", "loratadine", "tramadol", "insulin",
    "metformin", "amlodipine", "losartan", "nurofen", "disprin", "grandpa",
)

# Symptoms and conditions - mentioning one without naming a product means the
# customer wants advice about it.
SYMPTOM_WORDS = (
    "cough", "flu", "fever", "headache", "migraine", "infection", "allergy",
    "allergies", "asthma", "diabetes", "pressure", "ulcer", "diarrhoea",
    "diarrhea", "nausea", "vomiting", "pain", "rash", "thrush", "uti",
    "stomach", "sore throat", "congestion", "blocked nose", "cramps",
    "dizziness", "dizzy", "nauseous", "constipation", "heartburn",
    "toothache", "earache",
    "backache", "period pain", "ache", "aching", "hurts", "hurting", "sore",
    "swelling", "swollen", "burning", "bleeding",
)

# Generic words for the products themselves.
GENERIC_MED_WORDS = (
    "medication", "medicine", "medicines", "meds", "tablet", "tablets",
    "capsule", "capsules", "syrup", "pill", "pills", "drug", "drugs",
    "antibiotic", "antibiotics", "painkiller", "painkillers", "ointment",
    "drops", "inhaler", "dose", "dosage",
)

# Stock/price/order questions the bot IS allowed to answer from its tools.
_SHOPPING_PHRASES = (
    "do you have", "have you got", "do you stock", "do you sell", "do you carry",
    "available", "in stock", "out of stock",
    "how much is", "how much are", "how much for", "how much does",
    "price of", "the price", "cost of", "add ", "i want", "i'd like",
    "i would like", "buy", "order", "deliver", "give me", "sell",
    "can i get", "can i have", "could i get", "may i get", "i need",
    "let me get", "i'll take", "i will take", "get me", "sell me",
)

# "i have a headache" / "my son has a fever" is a request for help, not small talk.
_SYMPTOM_STATEMENT_PHRASES = (
    "i have", "i've got", "ive got", "i got", "i am having", "i'm having",
    "i am feeling", "i'm feeling", "i feel", "suffering from", "suffer from",
    "hurts", "hurting", "aching", "has a fever", "has a cough", "has pain",
    "been having", "been feeling",
)


def _any_word(text: str, words) -> bool:
    """Whole-word match, so 'pain' does not fire on 'painting'."""
    for word in words:
        if re.search(r"\b" + re.escape(word) + r"\b", text):
            return True
    return False


def is_medication_question(text) -> bool:
    """True when the message asks the bot for medication/prescription advice.

    Any True here must be answered with PHARMACIST_QUESTION_MESSAGE - never by
    the model. Pure and catalogue-independent, so it gives the same answer in
    the webhook, the test endpoint and the replay scripts.

    Shopping questions stay shopping: "do you have panadol?" and "how much is
    benylin" are stock/price questions, while "can i take panadol with
    antibiotics", "what can i take for a cough" and "is my script ready" are
    advice and go to a pharmacist.
    """
    if not text:
        return False
    raw = str(text).strip()
    if len(raw) < 3:
        return False
    low = re.sub(r"[^a-z0-9\s']", " ", raw.lower())
    low = " " + re.sub(r"\s+", " ", low).strip() + " "

    # 1) A prescription is pharmacist work whatever the wording.
    if _PRESCRIPTION_RE.search(low):
        return True

    # 2) What the message is about: a drug (named or by drug-name ending), a
    #    symptom, medicine in general, or a child's dose.
    named_drug = (_any_word(low, DRUG_NAME_WORDS)
                  or bool(_DRUG_SUFFIX_RE.search(low)))
    symptom = _any_word(low, SYMPTOM_WORDS)
    generic = _any_word(low, GENERIC_MED_WORDS)
    child = bool(_CHILD_DOSAGE_RE.search(low))

    # 3) Advice-shaped wording is clinical even when no product is named:
    #    "can i take these two together", "can i drink alcohol with this",
    #    "is it safe", "any side effects". A pharmacist, never the model.
    if _contains_phrase(low, _SELF_CLINICAL_PHRASES) is not None:
        return True
    if child or _FAMILY_USE_RE.search(low):
        return True

    if not (named_drug or symptom or generic):
        return False

    # 3b) Advice wording that needs a medicine or symptom to be clinical.
    if _contains_phrase(low, _CONTEXT_CLINICAL_PHRASES) is not None:
        return True

    # 4) "i need my medication" / "i've run out of my tablets" - a refill, not a sale.
    #    Refill wording wins over the shopping verbs, because "i need" is both.
    if _contains_phrase(low, _MED_REQUEST_PHRASES) is not None:
        return True

    # 5) Stock/price/order wording is plain shopping even when a symptom is
    #    mentioned: "can i get metformin", "i want some tablets for flu" and
    #    "do you have ibuprofen" are all product requests, not advice. Any
    #    advice phrasing was already caught in step 3/3b above, so this cannot
    #    let a clinical question through ("do you have something for a cough"
    #    matches "something for" first).
    if _contains_any(low, _SHOPPING_PHRASES) is not None:
        # "do you have painkillers" is still a stock question, so it reaches the
        # catalogue. "i need medication" names nothing to look up, so a
        # pharmacist takes it rather than the model guessing.
        stock_question = _contains_any(
            low, ("do you have", "have you got", "in stock", "out of stock",
                  "available", "how much", "price", "cost")) is not None
        if generic and not named_drug and not symptom and not stock_question:
            # "i need medication" names nothing to look up, so a pharmacist takes
            # it. "i want panado syrup" names a product ("panado") even though
            # "syrup" is only a generic word - that is an order, not advice.
            leftovers = [w for w in re.findall(r"[a-z0-9']+", low)
                         if len(w) > 2
                         and w not in _STOPWORDS
                         and w not in GENERIC_MED_WORDS]
            return not leftovers
        return False

    # 6) A symptom with no product named is a request for a recommendation.
    if symptom and not named_drug:
        return True

    # 7) "i have a fever", "my back hurts" - describing a symptom at the bot.
    if _contains_any(low, _SYMPTOM_STATEMENT_PHRASES) is not None:
        return True

    # 8) Any other question about a medicine ("is amoxicillin an antibiotic",
    #    "does benylin make you sleepy") is still a pharmacist question.
    if raw.rstrip().endswith("?"):
        return True
    stripped = low.strip()
    # Compare the first WORD, not a prefix: "amoxicillin" starts with "am" but
    # is not the question "am ...".
    if stripped.split(" ", 1)[0] in _TOPIC_QUESTION_STARTS:
        return True
    # A bare medicine request with no shopping words reads as a refill request.
    return bool(generic) or bool(symptom)


def is_purchase_intent(text: str) -> bool:
    """True when the customer is asking for the item (not just its price)."""
    if not text:
        return False
    lowered = " " + text.lower().strip() + " "
    if _contains_any(lowered, INFORMATIONAL_INTENT) and \
            _contains_any(lowered, PURCHASE_INTENT) is None:
        return False
    return _contains_any(lowered, PURCHASE_INTENT) is not None


# One line of a catalogue list the customer pasted back: "1. NAME - $6",
# "- NAME - $6" or "* NAME - $6". Two or more of them is a whole order.
_LIST_ENTRY = re.compile(r"^\s*(?:\d{1,3}\s*[.):\-]|[*•\-])\s*\S", re.M)

LIST_SELECTION_PHRASES = (
    "add these", "add them all", "add all", "all of them", "all these",
    "these to the cart", "the whole list", "add everything",
)


def is_multi_item_selection(text: str) -> bool:
    """True when the message is a list of products, not one product request.

    A pasted catalogue list ("1. X - $6 / 2. Y - $1") or an explicit "add these
    to the cart" is a whole order. The single-item "are you really sure you
    want <one item>?" double-check must never answer it: confirming it added
    that one line and silently dropped every other product the customer had
    just selected. The checkout summary still confirms the whole order.
    """
    if not text:
        return False
    lines = [line for line in text.splitlines() if line.strip()]
    priced = [line for line in lines if re.search(r"\$\s?\d", line)]
    if len(priced) >= 2:
        return True
    if len(lines) >= 2 and len(_LIST_ENTRY.findall(text)) >= 2:
        return True
    lowered = text.lower()
    return any(phrase in lowered for phrase in LIST_SELECTION_PHRASES)


def is_affirmative(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower().strip().rstrip("!. ")
    if lowered in AFFIRMATIVES:
        return True
    return lowered.startswith(("yes", "yeah", "yep", "sure", "correct", "yebo"))


def is_negative(text: str) -> bool:
    if not text:
        return False
    lowered = text.lower().strip().rstrip("!. ")
    if lowered in NEGATIVES:
        return True
    return lowered.startswith(("no", "nah", "nope", "not really", "i changed my mind"))


def sure_confirmation_message(item_name: str) -> str:
    """Double-check asked before the bot continues an unsure-sensitive order."""
    return (
        f"Just to confirm - are you really sure you want *{item_name}*?\n\n"
        "Reply *YES* to continue with your order.\n"
        "Reply *NO* and our pharmacist will review your request first."
    )


def extract_sure_check_item(last_bot_message: Optional[str]) -> Optional[str]:
    """Recover the item name from our own 'are you really sure' message."""
    if not last_bot_message or SURE_CHECK_MARKER not in last_bot_message.lower():
        return None
    match = re.search(r"want \*([^*]+)\*", last_bot_message)
    if match:
        return match.group(1).strip()
    return None


def last_assistant_message(history: Optional[List[Dict[str, str]]]) -> str:
    """Most recent bot message from the conversation history."""
    for msg in reversed(history or []):
        if msg.get("role") == "assistant":
            return (msg.get("content") or "").strip()
    return ""


# ===========================================================================
# 6. DELIVERY-DETAIL GUARDS - validate meaning, not just length
# ===========================================================================
#
# The delivery flow used to accept any reply that was long enough. A customer
# writing "i gave you my address already" (29 chars) had that sentence stored
# as their delivery address and the order went straight to payment. These
# helpers answer the two questions the step handlers actually need:
#   * is this message ABOUT the details, or IS it the detail?
#   * does it look like an address / a person's name at all?

_CONVERSATIONAL_MARKERS = (
    "i gave you", "i already gave", "i gave it", "i told you", "i already told",
    "already gave", "already told", "i just gave", "i said", "like i said",
    "as i said", "why are you asking", "i already said", "same as before",
    "same as last time", "use the same", "you have it", "you already have",
    "you know it", "ask me again", "stop asking",
    # shorthand people actually type
    "i gave u", "i told u", "u have it", "u already have", "already sent",
    "i sent", "i said", "like i said",
)

# Words that are never somebody's name - stops "ecocash" being saved as one,
# and stops "add them to the cart" being saved when the customer answers a
# stale name prompt with a shopping request.
_NON_NAME_WORDS = {
    "cash", "ecocash", "onemoney", "innbucks", "card", "delivery", "walkin",
    "walk", "pickup", "pick", "checkout", "yes", "no", "ok", "okay", "hi",
    "hello", "hey", "cart", "cancel", "thanks", "thank", "please", "order",
    "add", "remove", "delete", "buy", "get", "want", "need", "like", "would",
    "can", "could", "will", "should", "them", "these", "those", "it", "items",
    "item", "product", "products", "medicine", "medicines", "medication",
    "to", "the", "a", "an", "and", "or", "of", "for", "from", "with", "in",
    "on", "at", "my", "me", "i", "we", "us", "our", "you", "your", "is",
    "am", "are", "was", "were", "be", "this", "that", "they", "he", "she",
    "his", "her", "address", "phone", "number", "payment", "pay", "name",
    "collection", "collect", "branch", "stock", "available", "price",
}

# Answers that are not a name either. "not sure" was saved as a customer's
# name, and the delivery flow then called them "not sure" on the order.
_HEDGE_WORDS = {
    "not", "sure", "unsure", "maybe", "perhaps", "dunno", "dont", "don",
    "doesnt", "doesn", "didnt", "didn", "know", "idk", "none", "nothing",
    "nobody", "later", "skip", "instead", "whatever", "fine", "yeah", "yep",
    "nope", "pls", "plz", "am", "is", "was", "i", "im", "me", "my",
    "same", "again", "still", "wait", "hmm", "um", "uh", "what", "why",
}

# Street-type words. A delivery address needs one of these or a house number -
# a city on its own ("harare") is not enough to deliver to.
_STREET_WORDS = (
    "street", "st", "road", "rd", "avenue", "ave", "lane", "drive",
    "close", "crescent", "suburb", "section", "stand", "house", "plot",
    "block", "flat", "farm", "village",
)

_QUESTION_STARTS = (
    "what", "whats", "where", "which", "who", "how", "do you", "did you",
    "can you", "could you", "is it", "are you", "why",
)

_ADDRESS_WORDS = (
    "street", "st", "road", "rd", "avenue", "ave", "lane", "drive",
    "close", "crescent", "suburb", "section", "stand", "house", "plot",
    "block", "flat", "farm", "village", "city", "ushewekunze", "borrowdale",
    "mount pleasant", "avondale", "mabelreign", "waterfalls", "highlands",
    "greendale", "glen view", "glenview", "budiriro", "harare", "bulawayo",
    "gweru", "mutare", "masvingo", "kwekwe", "chitungwiza", "marondera",
    "ruwa", "norton", "epworth", "rezende", "angwa",
)

_CORRECTION_WORDS = (
    "sorry", "actually", "correction", "wrong", "mistake", "change", "update",
    "apologies", "apology", "oops", "not",
)


def is_conversational(text) -> bool:
    """True when the message is talk *about* the details, not the details."""
    if not text:
        return False
    raw = str(text).strip()
    low = " " + raw.lower() + " "
    if "?" in raw:
        return True
    if any(marker in low for marker in _CONVERSATIONAL_MARKERS):
        return True
    if low.strip().startswith(_QUESTION_STARTS):
        return True
    return False


def looks_like_address(text) -> bool:
    """True when `text` plausibly is a delivery address.

    Rejects questions and sentences about the address while still accepting
    short real ones such as "670 ushewekunze" (no street/road word at all).
    """
    if not text:
        return False
    raw = str(text).strip()
    if len(raw) < 6:
        return False
    if is_conversational(raw):
        return False

    low = raw.lower()
    # A house number plus a place name: "670 ushewekunze".
    if re.search(r"\d", raw) and len(raw.split()) >= 2:
        return True
    # "harare" / "bulawayo" on its own names a city, not a delivery point, so it
    # is not saved as the address - the customer is asked for the street too.
    if len(raw.split()) < 2 and not any(word in low.split() for word in _STREET_WORDS):
        return False
    if any(word in low for word in _ADDRESS_WORDS):
        return True
    # Two or more words of actual place-name content only counts when at least
    # one looks like a place, otherwise "farai rato" would pass as an address.
    words = [w for w in re.findall(r"[A-Za-z]+", raw) if len(w) > 2]
    if len(words) >= 2 and any(
            difflib.SequenceMatcher(None, w.lower(), a).ratio() >= 0.8
            for w in words for a in _ADDRESS_WORDS):
        return True
    return False


def looks_like_person_name(text) -> bool:
    """True when `text` plausibly is a customer's name."""
    if not text:
        return False
    raw = str(text).strip()
    if len(raw) < 2:
        return False
    if re.search(r"\d", raw):            # names do not contain phone/plot numbers
        return False
    if is_conversational(raw):
        return False
    low = raw.lower()
    if _contains_phrase(low, _ADDRESS_WORDS):
        return False
    if len(raw.split()) > 5:              # a sentence, not a name
        return False
    words = set(re.findall(r"[a-z]+", low))
    if words <= _NON_NAME_WORDS:
        return False
    # "not sure", "i dont know", "maybe later" - an answer about the name step,
    # never a name.
    if words & _HEDGE_WORDS:
        return False
    return True


def looks_like_correction(text) -> bool:
    """True when the customer is correcting an earlier detail.

    Tolerates typos ("sorr" for "sorry") which used to make the bot treat a
    name correction as a malformed phone number.
    """
    if not text:
        return False
    low = re.sub(r"[^a-z\s]", " ", str(text).lower())
    for token in low.split():
        if token in _CORRECTION_WORDS:
            return True
        for word in _CORRECTION_WORDS:
            if abs(len(token) - len(word)) <= 2 and \
                    difflib.SequenceMatcher(None, token, word).ratio() >= 0.85:
                return True
    return False


# "my name is Farai" / "name: Farai" - the message is supplying a value, so it
# must never be answered with "your name is *Old Name*" and then dropped.
_DETAIL_VALUE_RE = re.compile(
    r"\b(?:name|number|phone|address|location)\s*(?:is|to|:)\s*\S"
    r"|\b(?:call me|i am|i'm|im)\s+[a-z]",
    re.IGNORECASE,
)


def parse_detail_query(text) -> Optional[str]:
    """Which saved detail is the customer asking about ("address"/"phone"/"name")?

    Returns None when they are giving a value rather than asking a question.
    "my name is Farai Rato" sets the name; "what is my name" asks for it.
    """
    if not text:
        return None
    raw = str(text).strip()
    # Punctuation out of the way, so "what is my name?" still reads as a question.
    low = " " + re.sub(r"[^a-z0-9\s]", " ", raw.lower()).strip() + " "
    low = re.sub(r"\s+", " ", low)
    bare = low.strip()

    # A bare "address" / "my name" is still a question about that detail.
    if bare in {"address", "my address", "delivery address", "my delivery address"}:
        return "address"
    if bare in {"number", "my number", "phone", "my phone", "phone number"}:
        return "phone"
    if bare in {"name", "my name", "full name", "my full name"}:
        return "name"

    # Otherwise it has to be about the customer's OWN details - "what is the
    # name of this product" is a product question, not a name query.
    if not re.search(r"\b(?:my|our|your|mine)\b", low):
        return None

    # Whole words only: "what number do you have" is a question, and the "ave"
    # inside "have" is not an avenue.
    has_value = (bool(re.search(r"\d", low))
                 or _contains_phrase(low, _ADDRESS_WORDS) is not None
                 or bool(_DETAIL_VALUE_RE.search(raw)))

    if " address " in low or "delivery address" in low:
        return None if has_value else "address"
    if " number " in low or " phone " in low:
        return None if has_value else "phone"
    if " name " in low:
        return None if has_value else "name"
    return None


# The ways a customer actually asks for their name to be changed.
_NAME_PATTERNS = (
    re.compile(r"(?:my\s+)?(?:real\s+|full\s+)?name\s+(?:is|to)\s+(.+)$", re.I),
    re.compile(r"(?:please\s+)?(?:change|update|correct|fix|edit|set)\s+"
               r"(?:my\s+)?name\s+(?:to|is)\s+(.+)$", re.I),
    re.compile(r"(?:please\s+)?call\s+me\s+(.+)$", re.I),
)


def extract_name_correction(text) -> Optional[str]:
    """Pull the new name out of "my real name is Farai Emmanuel Rato".

    Also understands "change my name to ...", "update my name to ..." and
    "call me ..." - and returns None for "my name is not Farai" (a correction
    that never says what the right name is).
    """
    if not text:
        return None
    raw = str(text).strip()
    for pattern in _NAME_PATTERNS:
        match = pattern.search(raw)
        if not match:
            continue
        value = match.group(1).strip(" .!,")
        value = re.sub(r"^(?:actually|sorry|ok|okay|no)[\s,]+", "", value, flags=re.I)
        value = value.strip(" .!,")
        if not value or value.lower().startswith(("not ", "wrong", "incorrect")):
            continue
        return value
    return None


def phone_error_message(raw=None, known=None) -> str:
    """Contextual rejection - what we could not read, and what we already have."""
    seen = str(raw or "").strip()
    if len(seen) > 60:
        seen = seen[:57] + "..."

    parts = []
    if seen:
        parts.append(f"I couldn't read *{seen}* as a phone number.")
    parts.append(
        "Please send a valid *10-digit* phone number, e.g. "
        f"{PHONE_EXAMPLE} (or +263771234567)."
    )
    if known:
        parts.append(
            f"The number I have for you is *{known}* - reply *YES* to keep it, "
            "or send a different 10-digit number."
        )
    parts.append("_Tip: say 'cart' to view your cart, or 'cancel' to go back._")
    return "\n\n".join(parts)


def customer_intent_summary(text: str) -> str:
    """Small debug helper used by the scenario runner."""
    tags = []
    if is_uncertain_request(text):
        tags.append("uncertain")
    if is_medication_related(text):
        tags.append("medication")
    if is_purchase_intent(text):
        tags.append("purchase")
    if is_affirmative(text):
        tags.append("affirmative")
    if is_negative(text):
        tags.append("negative")
    return ",".join(tags) or "neutral"
