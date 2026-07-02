"""Seed pour les artistes similaires — ~80 artistes issus de 5 scènes."""

ARTISTS: dict[str, list[str]] = {
    "Française": [
        "Jul", "Ninho", "Gazo", "PLK", "Naps", "Hamza", "Nekfeu", "SDM",
        "SCH", "Freeze Corleone", "Kaaris", "PNL", "Lomepal", "Orelsan",
        "Laylow", "Gradur", "Damso", "Rim'K", "Vegedream", "Alonzo",
    ],
    "Américaine": [
        "Drake", "Travis Scott", "Kendrick Lamar", "Future", "Lil Baby",
        "Gunna", "21 Savage", "Lil Durk", "Rod Wave", "NBA YoungBoy",
        "J. Cole", "Meek Mill", "Post Malone", "The Weeknd", "SZA",
        "Tyler the Creator", "Frank Ocean", "Cardi B", "Megan Thee Stallion",
    ],
    "Espagnole": [
        "Bad Bunny", "J Balvin", "Maluma", "Anuel AA", "Myke Towers",
        "Jhay Cortez", "Rauw Alejandro", "Ozuna", "Nicki Nicole",
        "Bizarrap", "Mora", "Feid", "Sech", "Lunay",
    ],
    "Londonienne": [
        "Stormzy", "Dave", "Central Cee", "AJ Tracey", "Skepta",
        "Little Simz", "Headie One", "Aitch", "Digga D", "Unknown T",
        "Ghetts", "J Hus", "Giggs", "Jorja Smith", "Kano",
    ],
    "Africaine": [
        "Burna Boy", "Wizkid", "Davido", "Rema", "Asake",
        "Tems", "CKay", "Ayra Starr", "Fireboy DML", "BNXN",
        "Omah Lay", "Ruger", "Kizz Daniel", "Joeboy", "Oxlade",
        "Diamond Platnumz", "Innoss'B", "Fally Ipupa", "Harmonize", "Zuchu",
    ],
}


def run_seed() -> int:
    """Insère les artistes manquants. Idempotent — ne recrée pas les existants."""
    from extensions import db
    from models import SimilarArtist

    existing = {a.name for a in db.session.query(SimilarArtist.name).all()}
    added = 0
    for scene, names in ARTISTS.items():
        for name in names:
            if name not in existing:
                db.session.add(SimilarArtist(name=name, scene=scene))
                added += 1
    db.session.commit()
    return added
