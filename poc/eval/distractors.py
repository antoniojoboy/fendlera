"""
poc/eval/distractors.py - deterministic noise for scaling memory.

make_distractors(n, seed, exclude) returns n spoken-style statements in the
owner's voice. They are the realistic kind of noise that makes recall hard:
other people's streets, pets, jobs and numbers (near-misses for "my street",
"my dog"), passing remarks, and trivia.

Prefix-stable: the first k statements are identical whatever n is, so a
100-statement memory is exactly the start of a 1000-statement one. That is
what makes a trend across sizes a fair comparison.
"""
import random

NAMES = ["Jordan", "Priti", "Marco", "Leila", "Ben", "Ruth", "Omar", "Ivy",
         "Callum", "Zara", "Felix", "Nadia", "Grant", "Mei", "Oscar", "Tessa",
         "Raj", "Bianca", "Hugo", "Wren", "Dev", "Carmen", "Liam", "Sione",
         "Aisha", "Rory", "Elena", "Kofi", "Maddie", "Tariq"]
PLACES = ["Birchwood", "Hallam", "Sutter Bay", "Kelso", "Ridgeway",
          "Anvil Creek", "Marlow", "Pinehurst", "Coraki", "Eastvale",
          "Lindon", "Fairholme", "Wattle Downs", "Stirling Heights", "Redcliff"]
STREETS = ["Birch Road", "Larch Avenue", "Kestrel Way", "Station Street",
           "Quarry Lane", "Harbour Drive", "Mill Road", "Ocean Parade",
           "Railway Terrace", "Banksia Close", "Hill Street", "Canal Road"]
PETS = [("kelpie", "Rusty"), ("labrador", "Bonnie"), ("cat", "Mango"),
        ("greyhound", "Arrow"), ("budgie", "Kiwi"), ("cat", "Pickles"),
        ("staffy", "Tank"), ("beagle", "Scout"), ("rabbit", "Clover")]
JOBS = ["electrician", "dental nurse", "accountant", "bus driver", "chef",
        "physio", "teacher", "plumber", "graphic designer", "pharmacist"]
CARS = ["Hilux", "Mazda 3", "Corolla", "Ranger", "Outlander", "i30", "Golf",
        "CX-5", "Camry", "Swift"]
COLOURS = ["white", "grey", "blue", "red", "black", "silver", "green"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday"]
MONTHS = ["January", "March", "April", "June", "August", "October",
          "November"]
FOODS = ["sushi", "lasagne", "pho", "curry", "fish and chips", "tacos",
         "ramen", "a roast"]

TEMPLATES = [
    "my mate {name} lives in {place}, on {street}",
    "{name} at work has a {breed} called {pet}",
    "{name}'s kid is {n} and goes to {place} Primary",
    "the bus to {place} takes about {n2} minutes if you catch it early",
    "{name} reckons {food} is overrated, I don't mind it",
    "heard {name} is moving to {place} in {month}",
    "{name} drives a {colour} {car}, pretty sure it's second hand",
    "someone at the footy said the {place} Hawks play on {day}",
    "long day today, the traffic on {street} was a nightmare",
    "{name} is a {job} now, changed careers last year",
    "my cousin {name} got a new {breed}, named it {pet}",
    "{name} does the school run on {day}s I think",
    "we had {food} at {name}'s place, it was alright",
    "{name} said their rent went up to {n3} a week",
    "apparently {name} is doing a course in {place} every {day}",
    "the {place} markets are on {day} mornings",
    "{name}'s street is {street}, the one past the shops",
    "{name} was telling me about a trip to {place} in {month}",
]


def _fill(tpl: str, rng: random.Random, names, places) -> str:
    breed, pet = rng.choice(PETS)
    return tpl.format(
        name=rng.choice(names), place=rng.choice(places),
        street=rng.choice(STREETS), breed=breed, pet=pet,
        n=rng.randint(4, 12), n2=rng.choice([15, 20, 25, 35, 40, 45]),
        n3=rng.choice([420, 480, 510, 560, 600]), food=rng.choice(FOODS),
        month=rng.choice(MONTHS), colour=rng.choice(COLOURS),
        car=rng.choice(CARS), day=rng.choice(DAYS), job=rng.choice(JOBS))


def make_distractors(n: int, seed: int = 7, exclude: "set[str]" = frozenset()) -> "list[str]":
    """
    n statements, deterministic for a given seed and exclude set. Any name or
    place that appears in the dataset under test (exclude, lowercased words)
    is left out, so a distractor never accidentally answers a real question.
    """
    ex = {w.lower() for w in exclude}
    names = [x for x in NAMES if x.lower() not in ex]
    places = [x for x in PLACES if not (set(x.lower().split()) & ex)]
    rng = random.Random(seed)
    out, seen = [], set()
    while len(out) < n:
        s = _fill(rng.choice(TEMPLATES), rng, names, places)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
