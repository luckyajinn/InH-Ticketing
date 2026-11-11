"""
Two example departments, for the demo data and the tests: Mechanics, and
Cleaning & sanitization, each with a category and three common requests.
A real install starts with IT only; an admin adds its own departments.
"""

from tickets.models import Category, Department

EXAMPLE_DEPARTMENTS = [
    {
        "key": "mechanics", "name": "Mechanics", "entra_role": "Agent.Mechanics",
        "category": "Mechanics", "hint": "machines, equipment, facility repairs", "sort_order": 44,
        "common_requests": [
            "Equipment down: a machine won't start or has stopped",
            "Leak, unusual noise or vibration on equipment",
            "Facility repair: door, lighting, plumbing or HVAC",
        ],
    },
    {
        "key": "cleaning", "name": "Cleaning & sanitization", "entra_role": "Agent.Cleaning",
        "category": "Cleaning & sanitization", "hint": "spills, rooms, cleaning supplies", "sort_order": 46,
        "common_requests": [
            "Spill or mess that needs cleaning up",
            "Room or area needs cleaning and sanitizing",
            "Cleaning or sanitizing supplies running low",
        ],
    },
]
MECHANICS, CLEANING = (example["key"] for example in EXAMPLE_DEPARTMENTS)


def add_example_departments() -> dict[str, Category]:
    """Add the examples if they aren't there yet. Returns each one's category, by department key."""
    categories = {}
    for example in EXAMPLE_DEPARTMENTS:
        Department.objects.get_or_create(
            key=example["key"], defaults={"name": example["name"], "entra_role": example["entra_role"]},
        )
        categories[example["key"]], _ = Category.objects.get_or_create(
            name=example["category"],
            defaults={
                "department": example["key"], "hint": example["hint"], "sort_order": example["sort_order"],
                "subject_options": "\n".join(example["common_requests"]),
            },
        )
    return categories
