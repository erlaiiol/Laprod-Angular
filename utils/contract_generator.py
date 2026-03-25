from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from datetime import datetime

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
                'signature_date': str
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
    <b>Le Compositeur :</b> {contract_data['composer_name']}<br/>
    <b>Adresse :</b> {contract_data.get('composer_address', '______________________________')}<br/>
    <b>Email :</b> {contract_data.get('composer_email', '______________________________')}<br/>
    <br/>
    Ci-après désigné « le Compositeur »
    """
    story.append(Paragraph(composer_info, normal_style))
    story.append(Spacer(1, 0.3*cm))
    
    story.append(Paragraph("<b>ET</b>", normal_style))
    story.append(Spacer(1, 0.3*cm))
    
    # Interprète
    client_info = f"""
    <b>L'Interprète / Auteur :</b> {contract_data['client_name']}<br/>
    <b>Adresse :</b> {contract_data.get('client_address', '______________________________')}<br/>
    <b>Email :</b> {contract_data.get('client_email', '______________________________')}<br/>
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
        f"<b>Titre / Référence du beat :</b> {contract_data['track_title']}",
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
    
    duration_data = [
        ['Début :', contract_data['start_date']],
        ['Fin :', contract_data['end_date']],
        ['Durée totale :', contract_data.get('duration_text', '______________________')]
    ]
    
    duration_table = Table(duration_data, colWidths=[4*cm, 13*cm])
    duration_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(duration_table)
    story.append(Spacer(1, 0.2*cm))

    # Exception streaming
    streaming_exception_style = ParagraphStyle(
        'StreamingException',
        parent=normal_style,
        textColor=colors.HexColor('#0066cc'),
        fontSize=9,
        spaceAfter=6
    )
    story.append(Paragraph(
        "<b>️ EXCEPTION IMPORTANTE :</b> La durée du contrat ne s'applique <b>PAS</b> au streaming.",
        streaming_exception_style
    ))
    story.append(Paragraph(
        "Le beat <b>sous la voix de l'Interprète</b> peut rester disponible sur les plateformes de streaming "
        "(Spotify, Apple Music, YouTube, etc.) <b>indéfiniment</b> sans renouvellement du contrat ni requalification nécessaire.",
        normal_style
    ))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "À l'expiration, toute <b>autre forme d'exploitation</b> (reproduction mécanique, diffusion publique, etc.) doit cesser sauf renouvellement écrit.",
        normal_style
    ))
    
    # ============= 4. TERRITOIRE =============
    story.append(Paragraph("<b>4. Territoire</b>", section_style))
    story.append(Paragraph(
        f"La licence est accordée pour le territoire suivant : <b>{contract_data['territory']}</b>",
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
    platform_commission_amount = round(total_price * (platform_commission_pct / 100), 2)
    composer_revenue = round(total_price - platform_commission_amount, 2)

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

    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "<b>Répartition des droits d'auteur SACEM :</b>",
        normal_style
    ))
    story.append(Paragraph(
        f"Les parties conviennent de la répartition suivante des droits d'auteur à déclarer à la SACEM :",
        normal_style
    ))

    sacem_data = [
        ['Part du Compositeur (musique) :', f"{sacem_composer} %"],
        ['Part de l\'Interprète/Auteur (paroles/interprétation) :', f"{sacem_buyer} %"]
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
        "<i>Cette répartition doit être déclarée lors de l'enregistrement du titre à la SACEM. "
        "La déclaration à la SACEM est fortement recommandée pour protéger les droits des deux parties.</i>",
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
        "<b>️ CLAUSE DE RENÉGOCIATION ET REQUALIFICATION CONTRACTUELLE</b>",
        renegotiation_style
    ))
    story.append(Paragraph(
        "Le présent forfait constitue une rémunération initiale forfaitaire établie pour "
        "favoriser un marché équitable pour les musiciens indépendants français.",
        renegotiation_style
    ))
    story.append(Spacer(1, 0.1*cm))
    story.append(Paragraph(
        "<b>a) Droit à renégociation en cas d'exclusivité :</b> Si le beat est cédé sous licence exclusive, "
        "le Compositeur conserve le droit de renégocier les conditions du présent contrat, y compris pour "
        "l'exploitation en streaming, avec l'Interprète ou toute structure ayant acquis les droits d'exploitation.",
        renegotiation_style
    ))
    story.append(Spacer(1, 0.1*cm))
    story.append(Paragraph(
        "<b>b) Requalification pour déséquilibre manifeste (Art. L131-4 et L131-5 CPI) :</b> "
        "Conformément au Code de la Propriété Intellectuelle français, si le succès commercial du titre "
        "(nombre de streams, revenus générés, notoriété acquise) révèle un déséquilibre manifeste entre "
        "la rémunération forfaitaire initiale et les profits réalisés — même de manière différée ou inattendue — "
        "le Compositeur pourra demander la requalification du contrat devant les tribunaux compétents "
        "pour obtenir une rémunération proportionnelle aux recettes d'exploitation.",
        renegotiation_style
    ))
    story.append(Spacer(1, 0.1*cm))
    story.append(Paragraph(
        "<b>c) Protection mutuelle :</b> Cette clause vise à garantir un équilibre contractuel équitable "
        "entre les deux parties. Elle n'affecte en rien les droits légitimes de l'Interprète tant que "
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
    credit = contract_data.get('composer_credit', f"Prod. par {contract_data['composer_name']}")
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