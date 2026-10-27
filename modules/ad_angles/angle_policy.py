"""
Tunable policy for angle planning. Everything here is universal advertising structure and
contains no brand, industry, product or example copy: the people, offerings and moments are
generated fresh from each business's own website by the model. Edit this file to change how
sets are shaped; nothing else needs touching.
"""

# The persuasion levers an ad can pull. These describe how persuasion works, not any business.
LEVERS = {
    "identity_status": "who the reader wants to be seen as, or the role they are stuck playing",
    "vivid_fear_moment": "a specific time-stamped moment when something goes wrong and the reader feels it",
    "customer_story": "a short story about a person like the reader, with a name, a place and a turning point",
    "social_proof_numbers": "a concrete number that shows others already chose this: a real figure about the business (clients, years, branches, products) or what people like the reader say",
    "urgency_scarcity": "a reason to act now: the buyer's own deadline or event, or a real limited offer the business states",
    "authority_heritage": "years, scale, track record or credentials that settle the 'can I trust you' question",
    "objection_removal": "name the doubt the reader will not say out loud and answer it head on",
    "convenience_availability": "the friction or waiting the reader lives with today, removed",
    "aspiration_outcome": "the specific picture of life after it works, felt rather than described",
    "curiosity_contrarian": "a surprising claim or hard truth that makes the reader stop and want the answer",
}

# Every final set must contain at least one angle from each group (any lever inside a group counts).
REQUIRED_LEVER_GROUPS = (
    ("social_proof_numbers", "authority_heritage"),
    ("urgency_scarcity", "convenience_availability"),
    ("objection_removal",),
)

MAX_PER_LEVER = 2            # the same lever may appear at most this often in a final set
MIN_DISTINCT_LEVERS = 4      # a final set must use at least this many different levers
MIN_PROFILE_SEGMENTS = 2     # when buyer profiles are supplied, at least this many angles re-imagine one (capped by how many exist)
MAX_PROFILE_SEGMENTS = 3     # ...and no more than this many, so the set is not just the supplied profiles
MIN_OFF_SITE_PEOPLE = 2      # at least this many people the website never addresses
MAX_QUESTION_HOOKS = 2       # hooks that end with a question mark, at most
MIN_CANDIDATES = 12          # candidates written before selecting the final set
OFFERING_COVERAGE_SLOTS = 3  # how many core offerings must each be bought by someone in the set
REPAIR_ROUNDS = 2            # extra model calls allowed to fix a set that breaks the rules

# Universal buyer dimensions, so a set differs in KIND of person, not only in lever. Each candidate is
# tagged with one value per dimension; a final set may repeat any single value at most MAX_PER_DIMENSION_VALUE
# times. These are generic demographic buckets that apply to any business.
BUYER_DIMENSIONS = {
    "life_stage": ("student_or_first_job", "early_career", "growing_family", "established_professional",
                   "business_owner_or_leader", "senior_or_retired", "organisation"),
    "where_they_are": ("local", "abroad", "relocating", "rural_or_regional"),
    "buying_for": ("self", "family_member", "employer_or_organisation", "client_or_resale", "investment"),
}
MAX_PER_DIMENSION_VALUE = 2

# Offering-led angles lead with a real fact about the business from the fact bank (a price point, a sub-brand, a
# credit term, local production...) instead of a person's situation. A final set contains at least this many
# (when the fact bank has enough facts), and the model is given this many fact-led slots to write.
MIN_OFFERING_LED = 2
OFFERING_LED_CANDIDATES = 3

# Universal kinds of situation that make someone buy. The plan gives every slot a different one, so the angles in a
# set are about different moments, not five versions of the same scene.
SITUATION_TYPES = (
    "a deadline or event coming up",
    "a first-time purchase",
    "buying for someone else",
    "replacing something that failed or disappointed",
    "an upgrade after something went well",
    "shopping around and comparing options",
    "a recommendation from someone they trust",
    "a change of circumstances (a move, a new job, a new baby)",
)
