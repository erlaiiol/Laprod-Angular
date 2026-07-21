from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from datetime import datetime
from xml.sax.saxutils import escape as _xml_escape


def _esc(value) -> str:
    """Échappe une donnée dynamique destinée au mini-markup XML de ReportLab.

    composer_name, client_name, adresses, track_title, territoire et crédit
    proviennent des utilisateurs. Sans échappement, un '<' ou '&' casse la
    génération du contrat, et des balises injectées altèrent le document. Le
    markup <b>/<br/> volontaire reste écrit en clair, hors de _esc().
    """
    return _xml_escape('' if value is None else str(value))


def generate_contract_pdf(output_path, contract_data):
    """
    Génère un contrat d'autorisation d'exploitation conforme au droit français
    
    Args:
        contract_data: Dictionnaire contenant :
            {
                'track_title': str,
                'composer_name': str,
                'composer_address': str,
                'composer_email': str,
                'composer_credit': str,
                'client_name': str,
                'client_address': str,
                'client_email': str,
                'is_exclusive': bool,
                'start_date': str,
                'end_date': str,
                'duration_text': str,
                'territory': str,
                'mechanical_reproduction': bool,
                'public_show': bool,
                'streaming': bool,
                'arrangement': bool,
                'price': int,
                'percentage': int,
                'signature_place': str,
                'signature_date': str,
                'phonogram_producer_attested': bool,   # cf. article 1-bis
                'has_third_party_samples': bool,       # cf. article 9
                'sample_clearance_details': str,       # cf. article 9
                'buyer_declares_original_lyrics': bool, # cf. répartition SACEM (article 6)
            }
    """
    
    # Configuration du document
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # ============= STYLES =============
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=13,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=20,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#666666'),
        alignment=TA_CENTER,
        spaceAfter=30
    )
    
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=8,
        spaceBefore=12,
        fontName='Helvetica-Bold'
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=9.5,
        alignment=TA_JUSTIFY,
        spaceAfter=6
    )
    
    # ============= TITRE =============
    story.append(Paragraph(
        "CONTRAT D'AUTORISATION D'EXPLOITATION<br/>D'UNE COMPOSITION MUSICALE",
        title_style
    ))
    story.append(Paragraph(
        "(Contrat adapté au droit français)",
        subtitle_style
    ))
    
    # ============= ENTRE LES SOUSSIGNÉS =============
    story.append(Paragraph("<b>ENTRE LES SOUSSIGNÉS :</b>", section_style))
    
    # Compositeur
    composer_info = f"""
    <b>Le Compositeur :</b> {_esc(contract_data['composer_name'])}<br/>
    <b>Adresse :</b> {_esc(contract_data.get('composer_address', '______________________________'))}<br/>
    <b>Email :</b> {_esc(contract_data.get('composer_email', '______________________________'))}<br/>
    <br/>
    Ci-après désigné « le Compositeur »
    """
    story.append(Paragraph(composer_info, normal_style))
    story.append(Spacer(1, 0.3*cm))
    
    story.append(Paragraph("<b>ET</b>", normal_style))
    story.append(Spacer(1, 0.3*cm))
    
    # Interprète
    client_info = f"""
    <b>L'Interprète / Auteur :</b> {_esc(contract_data['client_name'])}<br/>
    <b>Adresse :</b> {_esc(contract_data.get('client_address', '______________________________'))}<br/>
    <b>Email :</b> {_esc(contract_data.get('client_email', '______________________________'))}<br/>
    <br/>
    Ci-après désigné « l'Interprète »
    """
    story.append(Paragraph(client_info, normal_style))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph("Ensemble appelés « les Parties ».", normal_style))
    story.append(Spacer(1, 0.5*cm))
    
    # ============= 1. OBJET DU CONTRAT =============
    story.append(Paragraph("<b>1. Objet du contrat</b>", section_style))
    story.append(Paragraph(
        "Le présent contrat a pour objet d'autoriser l'Interprète à utiliser la composition musicale suivante :",
        normal_style
    ))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        f"<b>Titre / Référence du beat :</b> {_esc(contract_data['track_title'])}",
        normal_style
    ))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "Cette autorisation porte exclusivement sur l'utilisation de la composition en vue :",
        normal_style
    ))
    story.append(Paragraph("• d'enregistrer une interprétation vocale (création d'un master),", normal_style))
    story.append(Paragraph("• d'exploiter ce master dans les limites prévues au présent contrat.", normal_style))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "<b>Le Compositeur reste seul titulaire des droits d'auteur sur la composition.</b>",
        normal_style
    ))

    # ============= 1-BIS. DROITS VOISINS (PRODUCTEUR DE PHONOGRAMME) =============
    story.append(Paragraph("<b>1-bis. Cession des droits voisins (producteur de phonogramme)</b>", section_style))
    story.append(Paragraph(
        "Indépendamment du droit d'auteur sur la composition visé à l'article 1, le fichier audio fourni "
        "(le « Phonogramme ») est susceptible de faire l'objet, au bénéfice du Compositeur, de droits "
        "voisins de producteur de phonogramme au sens de l'article L.213-1 du Code de la propriété "
        "intellectuelle. Le Compositeur cède à l'Interprète ces droits voisins dans la même mesure, pour "
        "la même durée, le même territoire et selon la même exclusivité que les droits d'auteur définis "
        "aux articles 2 à 4 ci-après.",
        normal_style
    ))
    if not contract_data.get('phonogram_producer_attested', False):
        story.append(Paragraph(
            "<i>Le Compositeur n'a pas confirmé, au moment de la mise en ligne du Phonogramme, être seul "
            "producteur de ce dernier. La présente cession des droits voisins est donc consentie dans la "
            "limite des droits dont le Compositeur dispose effectivement — notamment en cas de "
            "collaboration ou d'utilisation d'éléments sous licence de tiers.</i>",
            normal_style
        ))

    # ============= 2. NATURE DE LA LICENCE =============
    story.append(Paragraph("<b>2. Nature de la licence</b>", section_style))
    
    def checkbox(is_checked):
        return "[X]" if is_checked else "[ ]"
    
    is_exclusive = contract_data.get('is_exclusive', False)
    licence_text = f"""
    L'Interprète obtient une licence :<br/>
    {checkbox(not is_exclusive)} Licence NON exclusive<br/>
    {checkbox(is_exclusive)} Licence EXCLUSIVE (aucune autre licence ne sera délivrée pendant la durée du contrat)
    """
    story.append(Paragraph(licence_text, normal_style))
    
    # ============= 3. DURÉE =============
    story.append(Paragraph("<b>3. Durée</b>", section_style))

    is_streaming_only = contract_data.get('duration_text', '').startswith('Streaming seul')

    streaming_note_style = ParagraphStyle(
        'StreamingNote',
        parent=normal_style,
        textColor=colors.HexColor('#0066cc'),
        fontSize=9,
        spaceAfter=6
    )

    if is_streaming_only:
        story.append(Paragraph(
            "Ce contrat couvre exclusivement le <b>droit de streaming</b>, accordé pour la <b>durée légale "
            "de protection du droit d'auteur</b> (vie de l'auteur augmentée de 70 ans).",
            streaming_note_style
        ))
        story.append(Paragraph(
            "Le beat <b>sous la voix de l'Interprète</b> peut rester disponible sur les plateformes de streaming "
            "(Spotify, Apple Music, YouTube, etc.) pendant toute cette durée, sans renouvellement requis.<br/>"
            "<b>Aucun autre droit d'exploitation</b> (reproduction mécanique, diffusion publique, arrangement, etc.) "
            "n'est accordé par le présent contrat.",
            normal_style
        ))
    else:
        # Cellules en Paragraph : une Table reportlab ne coupe pas une chaîne
        # brute, et le libellé de terme légal dépasse la largeur de colonne.
        cell_style = ParagraphStyle('DurationCell', parent=normal_style, fontSize=9, spaceAfter=0)
        duration_data = [
            ['Début :',       Paragraph(_esc(contract_data['start_date']), cell_style)],
            ['Fin :',         Paragraph(_esc(contract_data['end_date']), cell_style)],
            ['Durée totale :', Paragraph(
                _esc(contract_data.get('duration_text') or '______________________'), cell_style)],
        ]
        duration_table = Table(duration_data, colWidths=[4*cm, 13*cm])
        duration_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('VALIGN',   (0, 0), (-1, -1), 'TOP'),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.append(duration_table)
        story.append(Spacer(1, 0.2*cm))
        story.append(Paragraph(
            "<b>Streaming inclus pour la durée légale de protection :</b> quelle que soit la durée indiquée "
            "ci-dessus, le droit de streaming est accordé pour la durée légale de protection du droit "
            "d'auteur (vie de l'auteur augmentée de 70 ans), sans renouvellement requis pendant cette période.",
            streaming_note_style
        ))
        story.append(Paragraph(
            "À l'expiration, l'Interprète conserve le droit de <b>continuer à exploiter les enregistrements "
            "déjà publiés</b> pendant la durée de la licence (cf. article 3-bis). Seules les <b>nouvelles "
            "exploitations</b> sous les autres formes concédées (reproduction mécanique, diffusion publique, etc.) "
            "doivent cesser, sauf renouvellement écrit.",
            normal_style
        ))
    
    # ============= 3-BIS. EXPIRATION, DROITS MORAUX ET RE-LICENCE =============
    story.append(Paragraph("<b>3-bis. Expiration, droits moraux et re-licence</b>", section_style))

    legal_expiry_style = ParagraphStyle(
        'LegalExpiry',
        parent=normal_style,
        fontSize=9,
        leftIndent=8,
        spaceAfter=5,
    )

    # Une échéance à durée légale (vie de l'auteur + 70 ans) n'est, en pratique,
    # jamais atteinte pendant l'exploitation commerciale de l'œuvre par les
    # Parties : elle correspond à l'entrée dans le domaine public, bien après le
    # décès du Compositeur. Rédiger cette échéance dans les mêmes termes qu'un
    # terme déterminé (« à l'expiration », « sans délai de carence »…) laisserait
    # croire au Compositeur qu'il retrouvera la main sur son œuvre à un horizon
    # commercial raisonnable — alors qu'une exclusivité consentie pour la durée
    # légale l'engage, dans les faits, à titre définitif.
    has_finite_term = bool(duration_text_val := contract_data.get('duration_text', '')) \
        and not is_streaming_only \
        and 'durée légale' not in duration_text_val.lower()

    story.append(Paragraph(
        "<b>1. Droits moraux permanents (art. L.121-1 CPI) :</b> "
        "Le Compositeur conserve ses droits moraux en permanence, quelles que soient les cessions de droits patrimoniaux "
        "effectuées par le présent contrat. Ces droits sont inaliénables et imprescriptibles.",
        legal_expiry_style
    ))

    if has_finite_term:
        story.append(Paragraph(
            "<b>2. Retour automatique des droits patrimoniaux :</b> "
            "À la date d'expiration indiquée à l'article 3, les droits patrimoniaux concédés reviennent "
            "automatiquement au Compositeur, sans qu'aucune formalité supplémentaire ne soit requise. "
            "L'Interprète n'est plus autorisé à créer de nouvelles exploitations commerciales de la composition après cette date.",
            legal_expiry_style
        ))

        story.append(Paragraph(
            "<b>3. Liberté de re-licence :</b> "
            "À l'expiration du présent contrat, le Compositeur est libre de concéder une nouvelle licence "
            "sur cette composition à tout tiers, y compris de manière exclusive, sans délai de carence et "
            "sans obligation d'en informer l'Interprète au préalable.",
            legal_expiry_style
        ))
    else:
        story.append(Paragraph(
            "<b>2. Portée pratique de l'échéance légale :</b> "
            "La durée retenue à l'article 3 est la durée légale de protection du droit d'auteur (vie du "
            "Compositeur augmentée de 70 ans). Cette échéance correspond à l'entrée de l'œuvre dans le domaine "
            "public et n'interviendra donc, dans les faits, jamais pendant l'exploitation commerciale de "
            "l'œuvre par les Parties. Les droits patrimoniaux concédés par le présent contrat n'ont ainsi pas "
            "vocation à faire retour au Compositeur de son vivant.",
            legal_expiry_style
        ))

        story.append(Paragraph(
            "<b>3. Absence de re-licence à échéance rapprochée :</b> "
            "Contrairement à une licence à durée déterminée, la présente licence n'ouvre au Compositeur aucune "
            "perspective réaliste de concéder une nouvelle licence sur cette composition avant l'entrée de "
            "l'œuvre dans le domaine public.",
            legal_expiry_style
        ))

    story.append(Paragraph(
        "<b>4. Sort des œuvres créées pendant la période de licence :</b> "
        "Les enregistrements et œuvres dérivées réalisés par l'Interprète <i>durant</i> la période de licence "
        "restent valides et peuvent continuer à être exploités dans les limites des droits concédés "
        "au moment de leur création. En revanche, l'Interprète ne pourra pas créer de nouvelles exploitations "
        "commerciales de la composition au-delà de la date d'expiration.",
        legal_expiry_style
    ))

    is_exclusive_contract = contract_data.get('is_exclusive', False)
    if is_exclusive_contract and has_finite_term:
        story.append(Paragraph(
            "<b>5. Fin de l'exclusivité :</b> "
            "À l'échéance de la présente licence exclusive, la composition redevient automatiquement disponible "
            "à la vente sur la plateforme LaProd et le Compositeur peut la licencier à de nouveaux acheteurs, "
            "y compris exclusivement, sans notification préalable à l'Interprète.",
            legal_expiry_style
        ))
    elif is_exclusive_contract:
        story.append(Paragraph(
            "<b>5. Portée de l'exclusivité :</b> "
            "La présente licence exclusive étant consentie pour la durée légale de protection du droit "
            "d'auteur, elle n'a pas vocation à prendre fin avant l'entrée de l'œuvre dans le domaine public. "
            "Le Compositeur ne pourra donc pas, de son vivant, proposer cette composition à un autre "
            "Interprète, y compris sur la plateforme LaProd.",
            legal_expiry_style
        ))

    story.append(Spacer(1, 0.3*cm))

    # ============= 4. TERRITOIRE =============
    story.append(Paragraph("<b>4. Territoire</b>", section_style))
    story.append(Paragraph(
        f"La licence est accordée pour le territoire suivant : <b>{_esc(contract_data['territory'])}</b>",
        normal_style
    ))
    
    # ============= 5. AUTORISATIONS ACCORDÉES =============
    story.append(Paragraph("<b>5. Autorisations accordées</b>", section_style))
    story.append(Paragraph(
        "L'autorisation couvre uniquement les points cochés ci-dessous :",
        normal_style
    ))
    story.append(Spacer(1, 0.2*cm))
    
    autorisations_data = [
        [f"{checkbox(contract_data['mechanical_reproduction'])} Reproduction mécanique", 
         "(CD, vinyles, téléchargements)"],
        [f"{checkbox(contract_data['public_show'])} Diffusion publique", 
         "(concerts, TV, radio, lieux publics)"],
        [f"{checkbox(contract_data['streaming'])} Streaming", 
         "(Spotify, Apple Music, YouTube…)"],
        [f"{checkbox(contract_data['arrangement'])} Arrangement / Adaptation du beat", 
         "(modification légère, mixage, structure)"],
    ]
    
    autorisations_table = Table(autorisations_data, colWidths=[7*cm, 10*cm])
    autorisations_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
    ]))
    story.append(autorisations_table)

    if contract_data.get('arrangement'):
        story.append(Paragraph(
            "<i>L'autorisation d'arrangement / adaptation s'exerce sans préjudice du droit moral "
            "inaliénable du Compositeur (art. L.121-1 CPI), qui conserve la faculté de s'opposer à toute "
            "dénaturation de l'œuvre.</i>",
            normal_style
        ))

    story.append(Paragraph(
        "<b>Toute autorisation non cochée est expressément refusée.</b>",
        normal_style
    ))
    
    # ============= 6. RÉMUNÉRATION =============
    story.append(Paragraph("<b>6. Rémunération</b>", section_style))
    story.append(Paragraph("La licence est accordée moyennant :", normal_style))
    story.append(Spacer(1, 0.2*cm))

    # Prix total payé par l'interprète
    total_price = contract_data['price']
    platform_commission_pct = contract_data.get('platform_commission', 10)
    platform_commission_amount = round(float(total_price) * (platform_commission_pct / 100), 2)
    composer_revenue = round(float(total_price) - platform_commission_amount, 2)

    remuneration_data = [
        ['Prix total payé par l\'Interprète :', f"{total_price} €"],
        ['Commission plateforme (LaProd) :', f"- {platform_commission_amount} € ({platform_commission_pct}%)"],
        ['Revenu net pour le Compositeur :', f"{composer_revenue} €"]
    ]

    remuneration_table = Table(remuneration_data, colWidths=[9*cm, 8*cm])
    remuneration_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TEXTCOLOR', (1, 0), (1, 0), colors.HexColor('#2ecc71')),
        ('TEXTCOLOR', (1, 1), (1, 1), colors.HexColor('#e74c3c')),
        ('FONTNAME', (1, 2), (1, 2), 'Helvetica-Bold'),
        ('TEXTCOLOR', (1, 2), (1, 2), colors.HexColor('#2ecc71')),
    ]))
    story.append(remuneration_table)

    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        "Le paiement du prix conditionne la validité du contrat.",
        normal_style
    ))

    # Pourcentages SACEM pour la répartition des droits d'auteur
    sacem_composer = contract_data.get('sacem_percentage_composer', 50)
    sacem_buyer = contract_data.get('sacem_percentage_buyer', 50)
    buyer_declares_original_lyrics = contract_data.get('buyer_declares_original_lyrics', False)

    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "<b>Répartition des droits d'auteur SACEM :</b>",
        normal_style
    ))

    if buyer_declares_original_lyrics:
        story.append(Paragraph(
            "L'Interprète a déclaré être l'auteur de paroles originales sur la composition. Les parties "
            "documentent ci-dessous, à titre indicatif, la répartition envisagée des droits d'auteur en "
            "vue de la déclaration du titre à la SACEM. <b>Le présent article ne constitue pas une "
            "déclaration SACEM et ne lie pas la SACEM</b>, dont la répartition définitive résulte de ses "
            "propres règles de répartition et de la déclaration effectivement déposée par les parties.",
            normal_style
        ))

        sacem_data = [
            ['Part du Compositeur (musique) :', f"{sacem_composer} %"],
            ['Part de l\'Interprète/Auteur (paroles) :', f"{sacem_buyer} %"]
        ]

        sacem_table = Table(sacem_data, colWidths=[10*cm, 7*cm])
        sacem_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
            ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#3498db')),
        ]))
        story.append(sacem_table)

        story.append(Paragraph(
            "<i>Cette répartition doit être confirmée lors de l'enregistrement du titre à la SACEM. "
            "La déclaration à la SACEM est fortement recommandée pour protéger les droits des deux parties.</i>",
            normal_style
        ))
    else:
        story.append(Paragraph(
            "L'Interprète n'a pas déclaré être l'auteur de paroles originales sur la composition : il "
            "n'est donc pas traité, dans le cadre du présent contrat, comme co-auteur au sens du droit "
            "d'auteur et ne perçoit à ce titre aucune part de répartition SACEM. Si l'Interprète exécute "
            "une prestation vocale ou instrumentale sur la composition, il peut, le cas échéant, être "
            "titulaire de droits voisins d'artiste-interprète (art. L.212-1 et suivants CPI), collectés "
            "séparément (ADAMI, SPEDIDAM) et hors du champ du présent contrat.",
            normal_style
        ))

    # Clause de renégociation / requalification
    renegotiation_style = ParagraphStyle(
        'Renegotiation',
        parent=normal_style,
        textColor=colors.HexColor('#e67e22'),
        fontSize=8.5,
        leftIndent=10,
        rightIndent=10,
        spaceAfter=8
    )
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph(
        "<b>RÉMUNÉRATION FORFAITAIRE (art. L.131-4 CPI)</b>",
        renegotiation_style
    ))
    story.append(Paragraph(
        "Le prix indiqué ci-dessus constitue une rémunération forfaitaire de la cession des droits "
        "d'auteur objet du présent contrat. Les parties reconnaissent que la base de calcul d'une "
        "rémunération proportionnelle aux recettes d'exploitation ne peut être pratiquement déterminée au "
        "moment de la conclusion du présent contrat, compte tenu de la nature du marché des licences de "
        "composition musicale en ligne. Si le beat est cédé sous licence exclusive, le Compositeur "
        "conserve en outre le droit de renégocier les conditions du présent contrat, y compris pour "
        "l'exploitation en streaming, avec l'Interprète ou toute structure ayant acquis les droits "
        "d'exploitation.",
        renegotiation_style
    ))
    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "<b>ACTION EN RÉVISION POUR LÉSION (art. L.131-5 CPI)</b>",
        renegotiation_style
    ))
    story.append(Paragraph(
        "Conformément à l'article L.131-5 du Code de la propriété intellectuelle, si le succès commercial "
        "du titre (nombre de streams, revenus générés, notoriété acquise) révèle, même de manière différée "
        "ou inattendue, une lésion de plus de sept douzièmes entre la rémunération forfaitaire perçue par "
        "le Compositeur et la valeur réelle de l'exploitation, le Compositeur pourra demander devant les "
        "tribunaux compétents la révision des conditions de prix du présent contrat, dans les délais "
        "prévus par la loi.",
        renegotiation_style
    ))
    story.append(Spacer(1, 0.1*cm))

    story.append(Paragraph(
        "<b>Protection mutuelle :</b> Ces clauses visent à garantir un équilibre contractuel équitable "
        "entre les deux parties. Elles n'affectent en rien les droits légitimes de l'Interprète tant que "
        "l'exploitation reste dans des proportions commerciales raisonnables et que le crédit du Compositeur "
        "est respecté. La déclaration à la SACEM est fortement recommandée pour renforcer la protection des deux parties.",
        renegotiation_style
    ))
    
    # ============= 7. PROPRIÉTÉ INTELLECTUELLE =============
    story.append(Paragraph("<b>7. Propriété intellectuelle</b>", section_style))
    story.append(Paragraph(
        "• Le Compositeur demeure titulaire exclusif de tous les droits d'auteur sur la composition.",
        normal_style
    ))
    story.append(Paragraph(
        "• L'Interprète ne peut en aucun cas revendiquer une part d'édition, de composition "
        "ou d'auteur de la musique, sauf accord écrit distinct.",
        normal_style
    ))
    story.append(Paragraph(
        "• Le master créé par l'Interprète est propriété de l'Interprète, sous réserve du "
        "respect des droits du Compositeur.",
        normal_style
    ))
    
    # ============= 8. MENTIONS OBLIGATOIRES =============
    story.append(Paragraph("<b>8. Mentions obligatoires</b>", section_style))
    credit = _esc(contract_data.get('composer_credit', f"Prod. par {contract_data['composer_name']}"))
    story.append(Paragraph(
        f"L'Interprète s'engage à créditer le Compositeur comme suit : "
        f"« <b>{credit}</b> » dans toutes les exploitations "
        f"(plateformes, crédits d'album, vidéos…).",
        normal_style
    ))
    
    # ============= 9. GARANTIES =============
    story.append(Paragraph("<b>9. Garanties</b>", section_style))
    story.append(Paragraph(
        "Le Compositeur garantit être titulaire des droits sur la composition et avoir pleine "
        "capacité pour accorder cette licence.",
        normal_style
    ))

    has_third_party_samples  = contract_data.get('has_third_party_samples', False)
    sample_clearance_details = contract_data.get('sample_clearance_details', '')
    if has_third_party_samples:
        story.append(Paragraph(
            f"Le Compositeur a déclaré, lors de la mise en ligne du beat, avoir utilisé un ou plusieurs "
            f"samples ou interpolations tiers, avec le statut de clearance suivant : "
            f"« {sample_clearance_details} ».",
            normal_style
        ))
    else:
        story.append(Paragraph(
            "Le Compositeur garantit ne pas avoir utilisé, dans la composition, de sample ou "
            "interpolation tiers non autorisé.",
            normal_style
        ))
    story.append(Paragraph(
        "Si cette déclaration s'avère inexacte, le Compositeur s'engage à indemniser l'Interprète des "
        "conséquences directes d'une réclamation de tiers portant sur les droits non déclarés (frais de "
        "défense raisonnables, dommages mis à la charge de l'Interprète), dans la limite du prix perçu "
        "au titre du présent contrat.",
        normal_style
    ))

    story.append(Paragraph(
        "L'Interprète garantit utiliser la composition seulement dans le cadre du présent contrat.",
        normal_style
    ))
    
    # ============= 10. RÉSILIATION =============
    story.append(Paragraph("<b>10. Résiliation</b>", section_style))
    story.append(Paragraph(
        "Le contrat pourra être résilié immédiatement en cas :",
        normal_style
    ))
    story.append(Paragraph("• de non-paiement,", normal_style))
    story.append(Paragraph("• d'utilisation non autorisée,", normal_style))
    story.append(Paragraph("• de violation grave des obligations contractuelles.", normal_style))
    
    # ============= 11. LOI APPLICABLE =============
    story.append(Paragraph("<b>11. Loi applicable – litiges</b>", section_style))
    story.append(Paragraph(
        "Le présent contrat est soumis au droit français. Tout litige sera soumis aux tribunaux "
        "du ressort du domicile du Compositeur.",
        normal_style
    ))
    
    story.append(Spacer(1, 1*cm))
    
    # ============= SIGNATURES =============
    signature_place = contract_data.get('signature_place', '___________________')
    signature_date = contract_data.get('signature_date', datetime.now().strftime('%d/%m/%Y'))
    
    story.append(Paragraph(
        f"<b>Fait à</b> {signature_place}, <b>le</b> {signature_date}",
        normal_style
    ))
    
    story.append(Spacer(1, 1*cm))
    
    # Récupérer les signatures numériques
    composer_signature = contract_data.get('composer_signature', contract_data['composer_name'])
    client_signature = contract_data.get('client_signature', contract_data['client_name'])
    
    signatures_data = [
        ['Signature du Compositeur', 'Signature de l\'Interprète'],
        ['(Précédée de la mention « Lu et approuvé »)', '(Précédée de la mention « Lu et approuvé »)'],
        ['Lu et approuvé', 'Lu et approuvé'],
        ['', ''],
        [composer_signature, client_signature]
    ]
    
    signatures_table = Table(signatures_data, colWidths=[8.5*cm, 8.5*cm], 
                             rowHeights=[0.5*cm, 0.4*cm, 0.4*cm, 1*cm, 0.5*cm])
    signatures_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, 1), 8),
        ('FONTNAME', (0, 2), (-1, 2), 'Helvetica-Oblique'),
        ('FONTSIZE', (0, 2), (-1, 2), 8),
        ('FONTNAME', (0, 4), (-1, 4), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 4), (-1, 4), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEABOVE', (0, 4), (-1, 4), 1, colors.black),
    ]))
    
    story.append(signatures_table)
    
    # Génération du PDF
    doc.build(story)
    
    return output_path