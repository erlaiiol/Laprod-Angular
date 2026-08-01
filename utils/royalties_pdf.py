"""
Génération d'un PDF "relevé de royalties" — snapshot horodaté de la cap-table
déclarative d'un titre (qui possède quel pourcentage, à quel titre, confirmé
ou non). Purement déclaratif comme le module lui-même : ce document n'engage
aucun paiement, c'est l'artefact que le porteur du titre transmet en dehors de
LaProd (label, comptable, PRO/SACEM, nouveau collaborateur qui rejoint le
projet) pour attester d'un état des droits à un instant T.

Même stack que invoice_generator.py (ReportLab, génération en mémoire, aucune
persistance disque) — un relevé de royalties est un rapport à la demande, pas
un document contractuel devant survivre en base comme un contrat signé.
"""

import io
from datetime import datetime
from decimal import Decimal
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_C_TEXT    = colors.HexColor('#1a1a1a')
_C_SECTION = colors.HexColor('#2c3e50')
_C_GREEN   = colors.HexColor('#10b981')
_C_ORANGE  = colors.HexColor('#f97316')
_C_MUTED   = colors.HexColor('#6b7280')
_C_BORDER  = colors.HexColor('#d1d5db')

_PAGE_W = A4[0] - 4 * cm

_ROLE_LABELS = {
    'topliner':     'Topliner',
    'beatmaker':    'Beatmaker',
    'mix_engineer': 'Ingénieur mix/master',
    'label':        'Label',
    'producer':     'Producteur',
    'other':        'Autre',
}


def _esc(value) -> str:
    """Toute donnée utilisateur (nom de titre, de collaborateur) DOIT passer
    par ce helper avant d'entrer dans un Paragraph — cf. invoice_generator.py."""
    return _xml_escape('' if value is None else str(value))


def _styles():
    base = getSampleStyleSheet()
    return dict(
        title=ParagraphStyle('RoyTitle', parent=base['Normal'], fontSize=14,
                              textColor=_C_SECTION, fontName='Helvetica-Bold', spaceAfter=2),
        subtitle=ParagraphStyle('RoySubtitle', parent=base['Normal'], fontSize=8,
                                 textColor=_C_MUTED, spaceAfter=0),
        label=ParagraphStyle('RoyLabel', parent=base['Normal'], fontSize=8,
                              textColor=_C_MUTED, fontName='Helvetica-Bold', spaceAfter=1),
        normal=ParagraphStyle('RoyNormal', parent=base['Normal'], fontSize=9,
                               textColor=_C_TEXT, spaceAfter=2),
        small=ParagraphStyle('RoySmall', parent=base['Normal'], fontSize=7.5,
                              textColor=_C_MUTED, spaceAfter=2),
        footer=ParagraphStyle('RoyFooter', parent=base['Normal'], fontSize=7,
                               textColor=_C_MUTED, alignment=TA_CENTER, spaceAfter=0),
    )


def generate_royalties_statement(track, splits: list, total_percentage: Decimal) -> bytes:
    """
    track            : instance Track (title, composer_user)
    splits           : liste de TrackSplit (déjà triés par created_at)
    total_percentage : Decimal — somme des pourcentages attribués
    """
    st = _styles()
    story = []

    generated_at = datetime.now().strftime('%d/%m/%Y à %H:%M')
    composer_name = track.composer_user.username if track.composer_user else '—'

    # ── En-tête ────────────────────────────────────────────────────────────────
    header_data = [
        [
            Paragraph('<b>LaProd</b>', st['title']),
            Paragraph(
                'Relevé de royalties',
                ParagraphStyle('RoyDocR', parent=st['normal'], alignment=TA_RIGHT,
                                fontName='Helvetica-Bold', textColor=_C_SECTION),
            ),
        ],
        [
            Paragraph('Snapshot déclaratif — aucun paiement automatisé', st['subtitle']),
            Paragraph(f'Généré le {generated_at}',
                       ParagraphStyle('RoyDateR', parent=st['small'], alignment=TA_RIGHT)),
        ],
    ]
    t = Table(header_data, colWidths=[_PAGE_W * 0.55, _PAGE_W * 0.45])
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.3 * cm))
    story.append(Table([['']], colWidths=[_PAGE_W],
                        style=TableStyle([('LINEBELOW', (0, 0), (0, 0), 1, _C_BORDER)])))
    story.append(Spacer(1, 0.5 * cm))

    # ── Titre concerné ────────────────────────────────────────────────────────
    story.append(Paragraph('TITRE', st['label']))
    story.append(Paragraph(_esc(track.title), st['normal']))
    story.append(Paragraph(f'Compositeur : {_esc(composer_name)}', st['small']))
    story.append(Spacer(1, 0.5 * cm))

    # ── Tableau des parts ─────────────────────────────────────────────────────
    table_data = [[
        Paragraph('<b>INTERVENANT</b>', ParagraphStyle('ThName', parent=st['small'], fontName='Helvetica-Bold')),
        Paragraph('<b>RÔLE</b>', ParagraphStyle('ThRole', parent=st['small'], fontName='Helvetica-Bold')),
        Paragraph('<b>PART</b>', ParagraphStyle('ThPct', parent=st['small'], fontName='Helvetica-Bold', alignment=TA_RIGHT)),
        Paragraph('<b>STATUT</b>', ParagraphStyle('ThStatus', parent=st['small'], fontName='Helvetica-Bold', alignment=TA_RIGHT)),
    ]]

    for s in splits:
        name = s.user.username if s.user else s.external_name
        role_label = _ROLE_LABELS.get(s.role.value, 'Autre')
        is_confirmed = s.status.value == 'confirmed'
        status_color = _C_GREEN if is_confirmed else _C_ORANGE
        status_label = 'Confirmée' if is_confirmed else 'Déclarée'

        table_data.append([
            Paragraph(_esc(name), st['normal']),
            Paragraph(_esc(role_label), st['normal']),
            Paragraph(f'{s.percentage} %',
                      ParagraphStyle('Pct', parent=st['normal'], alignment=TA_RIGHT, fontName='Helvetica-Bold')),
            Paragraph(status_label,
                      ParagraphStyle('Status', parent=st['small'], alignment=TA_RIGHT, textColor=status_color)),
        ])

    # Ligne total
    total_color = _C_GREEN if total_percentage >= 100 else _C_ORANGE
    table_data.append([
        Paragraph('<b>TOTAL ATTRIBUÉ</b>', ParagraphStyle('TotalLbl', parent=st['normal'],
                                                            fontName='Helvetica-Bold', textColor=_C_SECTION)),
        Paragraph('', st['normal']),
        Paragraph(f'<b>{total_percentage} %</b>', ParagraphStyle('TotalPct', parent=st['normal'],
                                                                    alignment=TA_RIGHT, fontName='Helvetica-Bold',
                                                                    textColor=total_color)),
        Paragraph('', st['small']),
    ])

    n = len(table_data)
    t = Table(table_data, colWidths=[_PAGE_W * 0.38, _PAGE_W * 0.28, _PAGE_W * 0.17, _PAGE_W * 0.17])
    t.setStyle(TableStyle([
        ('FONTSIZE',      (0, 0), (-1, -1),     9),
        ('BOTTOMPADDING', (0, 0), (-1, -1),     5),
        ('TOPPADDING',    (0, 0), (-1, -1),     4),
        ('VALIGN',        (0, 0), (-1, -1),     'TOP'),
        ('LINEBELOW',     (0, 0), (-1, 0),      0.5, _C_BORDER),
        ('LINEABOVE',     (0, n - 1), (-1, n - 1), 1, _C_SECTION),
        ('BACKGROUND',    (0, n - 1), (-1, n - 1), colors.HexColor('#f8fafc')),
    ]))
    story.append(t)

    if total_percentage < 100:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(
            f"Cap-table incomplète à la date de génération : {100 - total_percentage} % non attribués.",
            ParagraphStyle('Incomplete', parent=st['small'], textColor=_C_ORANGE),
        ))

    # ── Pied de page ──────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.6 * cm))
    story.append(Table([['']], colWidths=[_PAGE_W],
                        style=TableStyle([('LINEABOVE', (0, 0), (0, 0), 0.5, _C_BORDER)])))
    story.append(Spacer(1, 0.25 * cm))
    story.append(Paragraph(
        "Document déclaratif généré automatiquement par LaProd, sans valeur d'engagement de paiement. "
        "Une part \"Déclarée\" n'a pas encore été confirmée par son titulaire.",
        st['footer'],
    ))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    doc.build(story)
    return buf.getvalue()
