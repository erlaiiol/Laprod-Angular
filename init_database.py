#!/usr/bin/env python3
"""
Script d'initialisation de la base de données
Crée les catégories par défaut et migre les anciens tags
"""

from app import app
from models import db, Category, Tag, Track

def init_categories():
    """Créer les catégories par défaut"""
    print(" Initialisation des catégories...")
    
    default_categories = [
        ('harmonic', 'Tags relatifs à l\'harmonie, gammes, tonalités'),
        ('structural', 'Tags relatifs à la structure du morceau'),
        ('rhythmic', 'Tags relatifs au rythme et patterns'),
        ('mood', 'Tags relatifs à l\'ambiance et l\'émotion'),
        ('instrument', 'Tags relatifs aux instruments utilisés'),
        ('genre', 'Tags relatifs aux genres musicaux'),
        ('other', 'Tags divers')
    ]
    
    created_count = 0
    
    for name, description in default_categories:
        existing = db.session.query(Category).filter_by(name=name).first()
        if not existing:
            category = Category(name=name)
            db.session.add(category)
            created_count += 1
            print(f"   Catégorie créée: {name}")
        else:
            print(f"  ️  Catégorie existante: {name}")
    
    try:
        db.session.commit()
        print(f"\n {created_count} catégorie(s) créée(s)\n")
        return True
    except Exception as e:
        db.session.rollback()
        print(f"\n Erreur lors de la création des catégories: {e}\n")
        return False


def migrate_existing_tags():
    """
    Migrer les tags existants vers le nouveau système avec catégories
    Tous les anciens tags seront assignés à la catégorie 'other' par défaut
    """
    print(" Migration des tags existants...")
    
    # Récupérer la catégorie 'other'
    other_category = db.session.query(Category).filter_by(name='other').first()
    if not other_category:
        print(" Catégorie 'other' introuvable. Exécutez d'abord init_categories()")
        return False
    
    # Récupérer tous les tags sans catégorie
    orphan_tags = db.session.query(Tag).filter_by(category_id=None).all()
    
    if not orphan_tags:
        print("  ️  Aucun tag à migrer\n")
        return True
    
    print(f"   {len(orphan_tags)} tag(s) à migrer...")
    
    migrated_count = 0
    for tag in orphan_tags:
        tag.category_id = other_category.id
        migrated_count += 1
    
    try:
        db.session.commit()
        print(f"   {migrated_count} tag(s) migré(s) vers 'other'\n")
        return True
    except Exception as e:
        db.session.rollback()
        print(f"   Erreur lors de la migration: {e}\n")
        return False


def suggest_tag_categorization():
    """
    Suggérer une catégorisation intelligente des tags existants
    basée sur des mots-clés
    """
    print(" Suggestions de catégorisation des tags...")
    
    # Mots-clés par catégorie
    categorization_hints = {
        'harmonic': ['major', 'minor', 'chord', 'scale', 'key', 'sharp', 'flat', 
                     'pentatonic', 'diatonic', 'chromatic', 'seventh', 'sus', 'dim'],
        'structural': ['intro', 'verse', 'chorus', 'bridge', 'outro', 'drop', 
                       'breakdown', 'build', 'section', 'part'],
        'rhythmic': ['syncopated', 'triplet', 'swing', 'straight', 'groove', 
                     'pattern', 'beat', 'tempo', 'fast', 'slow'],
        'mood': ['dark', 'bright', 'happy', 'sad', 'melancholic', 'uplifting', 
                 'calm', 'energetic', 'aggressive', 'peaceful', 'emotional'],
        'instrument': ['piano', 'guitar', 'bass', 'drum', 'synth', '808', 'vocal', 
                       'strings', 'brass', 'horn', 'pad', 'lead'],
        'genre': ['trap', 'house', 'techno', 'hip-hop', 'jazz', 'rock', 'pop', 
                  'edm', 'lofi', 'ambient', 'drill', 'dubstep']
    }
    
    # Récupérer tous les tags
    all_tags = db.session.query(Tag).all()
    suggestions = []
    
    for tag in all_tags:
        tag_lower = tag.name.lower()
        current_category = tag.category_obj.name if tag.category_obj else 'none'
        
        # Si le tag est déjà bien catégorisé (pas 'other'), on skip
        if current_category != 'other' and current_category != 'none':
            continue
        
        # Chercher une catégorie correspondante
        for category, keywords in categorization_hints.items():
            if any(keyword in tag_lower for keyword in keywords):
                suggestions.append({
                    'tag': tag.name,
                    'current': current_category,
                    'suggested': category
                })
                break
    
    if suggestions:
        print(f"\n   {len(suggestions)} suggestion(s) de recatégorisation :\n")
        for sugg in suggestions[:20]:  # Limiter l'affichage
            print(f"    • '{sugg['tag']}': {sugg['current']} → {sugg['suggested']}")
        
        if len(suggestions) > 20:
            print(f"    ... et {len(suggestions) - 20} autres suggestions")
    else:
        print("  ️  Aucune suggestion de recatégorisation\n")
    
    return suggestions


def display_statistics():
    """Afficher des statistiques sur la base de données"""
    print(" Statistiques de la base de données\n")
    
    categories = db.session.query(Category).all()
    total_tags = db.session.query(Tag).count()
    total_tracks = db.session.query(Track).count()
    
    print(f"  • Nombre total de tracks: {total_tracks}")
    print(f"  • Nombre total de tags: {total_tags}")
    print(f"  • Nombre de catégories: {len(categories)}\n")
    
    print("  Distribution des tags par catégorie:")
    for cat in categories:
        tag_count = db.session.query(Tag).filter_by(category_id=cat.id).count()
        percentage = (tag_count / total_tags * 100) if total_tags > 0 else 0
        bar = '█' * int(percentage / 5)
        print(f"    {cat.name:15} {tag_count:4} tags {bar:20} {percentage:.1f}%")
    
    print()


def main():
    """Fonction principale"""
    print("\n" + "="*60)
    print("   INITIALISATION DE LA BASE DE DONNÉES - LAPROD")
    print("="*60 + "\n")
    
    with app.app_context():
        # 1. Initialiser les catégories
        if not init_categories():
            print(" Échec de l'initialisation. Arrêt du script.")
            return
        
        # 2. Migrer les tags existants
        if not migrate_existing_tags():
            print("️  Migration partielle. Certains tags n'ont pas été migrés.")
        
        # 3. Suggérer des catégorisations
        suggestions = suggest_tag_categorization()
        
        # 4. Afficher les statistiques
        display_statistics()
        
        print("="*60)
        print("   Initialisation terminée !")
        print("="*60 + "\n")
        
        # Proposer d'appliquer les suggestions
        if suggestions:
            print(" Pour appliquer automatiquement les suggestions de catégorisation,")
            print("   exécutez : python init_database.py --apply-suggestions\n")


if __name__ == '__main__':
    import sys
    
    if '--apply-suggestions' in sys.argv:
        print("\n Application des suggestions de catégorisation...\n")
        with app.app_context():
            # TODO: Implémenter l'application automatique des suggestions
            print("️  Fonctionnalité à implémenter\n")
    else:
        main()